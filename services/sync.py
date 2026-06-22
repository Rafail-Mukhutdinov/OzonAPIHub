"""
Модуль синхронизации данных с Ozon API.
Оптимизирован для массовой обработки без перегрузки БД.
"""

import os
import logging
import asyncio
from typing import Union
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from db.database import User, Order, OrderPosting, OrderProduct, OzonCredential, SessionLocal, SyncStatus
from services.enrichment import enrich_posting_from_ozon
from services.ozon import ozon_fbo_list_async
from utils.encryption import decrypt_credential
from utils.common import valid_posting_number, to_msk, to_msk_date, parse_ozon_datetime
from utils.logging_config import log_user_event

logger = logging.getLogger("OzonAPIHub")

# Настройки из .env
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '24'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')
ENRICH_CONCURRENCY = 2 # Снизили параллельность для стабильности на локальной машине

def _get_now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_latest_order_datetime(db: Session, user_id: int) -> Union[datetime, None]:
    """
    Надежно находит дату последнего заказа пользователя, обходя ограничения
    лексикографического сравнения строк в БД.
    Проверяет последние 1000 записей из Order и OrderPosting.
    """
    values = []

    # Берем последние по ID записи (обычно они самые свежие)
    raw_values = db.query(Order.created_at).filter(
        Order.user_id == user_id,
        Order.created_at.isnot(None)
    ).order_by(Order.id.desc()).limit(1000).all()

    posting_values = db.query(OrderPosting.created_at).filter(
        OrderPosting.user_id == user_id,
        OrderPosting.created_at.isnot(None)
    ).order_by(OrderPosting.id.desc()).limit(1000).all()

    for row in raw_values + posting_values:
        dt = parse_ozon_datetime(row[0])
        if dt:
            # Приводим к UTC naive для консистентного сравнения
            values.append(dt.astimezone(timezone.utc).replace(tzinfo=None))

    return max(values) if values else None

async def sync_user_orders(user: User, db: Session) -> bool:
    """Синхронизирует заказы для ОДНОГО пользователя с использованием Smart Gap Filling."""
    try:
        active_cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user.id,
            OzonCredential.is_active == True
        ).first()
        
        if not active_cred: return False

        now = _get_now_utc()

        # Smart Gap Filling Logic - надежный поиск последней даты
        last_order_dt = get_latest_order_datetime(db, user.id)

        if last_order_dt:
            # Если заказы были, берем с момента последнего заказа до сейчас
            since_dt = last_order_dt
        else:
            # Если заказов нет, берем за последние 30 дней
            since_dt = now - timedelta(days=30)

        # Убеждаемся, что окно не слишком большое для регулярной синхронизации
        if since_dt < now - timedelta(days=60):
            since_dt = now - timedelta(days=60)

        # Не добавляем +1 секунду, чтобы не терять заказы на стыке
        since_iso = since_dt.replace(microsecond=0).isoformat().split('+')[0] + 'Z'
        to_iso = now.replace(microsecond=0).isoformat().split('+')[0] + 'Z'

        # Обновляем время последней проверки для адаптивного планировщика
        status = db.query(SyncStatus).filter(SyncStatus.user_id == user.id).first()
        if status:
            status.updated_at = now
            db.commit()

        client_id, api_key = decrypt_credential(active_cred.client_id_encrypted), decrypt_credential(active_cred.api_key_encrypted)
        if not client_id or not api_key: return False

        total_saved, offset, limit = 0, 0, 50
        new_pns = set()

        while True:
            data = await ozon_fbo_list_async(
                client_id=client_id, api_key=api_key,
                filter_dict={'since': since_iso, 'to': to_iso},
                limit=limit, offset=offset,
                sort_dir="DESC" # Свежие заказы запрашиваем в первую очередь
            )

            # Robust parsing: проверка типа ответа
            if not isinstance(data, dict):
                logger.warning(f"Ozon API returned unexpected format for user {user.id}: expected dict, got {type(data)}")
                break

            items = data.get("result", [])
            if not isinstance(items, list):
                logger.warning(f"Ozon API 'result' is not a list for user {user.id}: {type(items)}")
                break

            if not items: break
            
            # Предварительно проверяем, какие из этих постингов уже обогащены
            fetched_pns = [o.get('posting_number') for o in items if isinstance(o, dict) and valid_posting_number(o.get('posting_number'))]
            existing_norm_pns = set()
            if fetched_pns:
                norm_rows = db.query(OrderPosting.posting_number).filter(
                    OrderPosting.user_id == user.id,
                    OrderPosting.posting_number.in_(fetched_pns)
                ).all()
                existing_norm_pns = {r[0] for r in norm_rows}

            for o in items:
                if not isinstance(o, dict):
                    logger.warning(f"Skipping order item: expected dict, got {type(o)}")
                    continue

                pn = o.get('posting_number')
                # Сохраняем в сырую таблицу (вернет True если новый или статус изменился)
                is_active_change = save_order_for_user(db, user, o)

                # Добавляем в очередь на обогащение если:
                # - это новый заказ/изменение статуса
                # - ИЛИ заказа нет в нормализованной таблице (был пропущен или ошибка)
                if is_active_change or (pn not in existing_norm_pns):
                    total_saved += 1
                    if valid_posting_number(pn):
                        new_pns.add(pn)
            
            if len(items) < limit: break
            offset += limit

        if total_saved > 0:
            log_user_event(user.id, f"Найдено новых заказов: {total_saved}. Запуск обогащения...")
            if ENRICH_ON_FETCH:
                await run_enrichment_batch(list(new_pns), user.id)

        return total_saved > 0
    except Exception as e:
        logger.error(f"User {user.id}: sync_user_orders error: {e}", exc_info=True)
        return False

def save_order_for_user(db: Session, user: User, order_data: dict) -> bool:
    if not isinstance(order_data, dict): return False
    posting_number = order_data.get('posting_number')
    if not posting_number: return False
    try:
        user_id = user.id if hasattr(user, 'id') else user
        existing = db.query(Order).filter(Order.user_id == user_id, Order.posting_number == posting_number).first()
        status = order_data.get('status')

        # Нормализация даты перед сохранением
        raw_created_at = order_data.get('created_at')
        dt_created = parse_ozon_datetime(raw_created_at)
        normalized_created_at = dt_created.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') if dt_created else raw_created_at

        if existing:
            if existing.status != status:
                existing.status = status
                existing.updated_at = normalized_created_at
                db.commit()
                return True # Изменение статуса тоже считаем активностью
            return False
        new_order = Order(
            user_id=user_id,
            order_id=order_data.get('order_id'),
            posting_number=posting_number, status=status,
            created_at=normalized_created_at,
            updated_at=normalized_created_at,
            data=order_data
        )
        db.add(new_order)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving order {posting_number}: {e}")
        db.rollback()
        return False

async def fetch_and_save_orders_async(since: str, to: str, status_f: str, limit: int, offset: int, user_id: int, db: Session) -> dict:
    # Используется для API и Backfill
    try:
        user = db.query(User).filter(User.id == user_id).first()
        cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
        if not user or not cred: return {"saved": 0, "fetched": 0, "orders": []}
        
        res = await ozon_fbo_list_async(
            client_id=decrypt_credential(cred.client_id_encrypted),
            api_key=decrypt_credential(cred.api_key_encrypted),
            filter_dict={'since': since, 'to': to, 'status': status_f} if status_f else {'since': since, 'to': to},
            limit=limit, offset=offset
        )

        # Robust parsing
        if not isinstance(res, dict):
            return {"saved": 0, "fetched": 0, "error": f"Unexpected API response type: {type(res)}", "orders": []}

        items = res.get("result", [])
        if not isinstance(items, list):
            return {"saved": 0, "fetched": 0, "error": f"API 'result' is not a list: {type(items)}", "orders": []}

        saved = 0
        valid_orders = []
        for o in items:
            if not isinstance(o, dict): continue
            if save_order_for_user(db, user, o): saved += 1
            valid_orders.append(o)
        return {"saved": saved, "fetched": len(items), "orders": valid_orders}
    except Exception as e:
        logger.error(f"fetch_and_save_orders_async error: {e}")
        return {"saved": 0, "fetched": 0, "error": str(e), "orders": []}

async def run_enrichment_batch(pns: list[str], user_id: int):
    """
    Массовое обогащение.
    Создает отдельную сессию на каждый запрос для предотвращения гонки состояний (Race Condition).
    """
    if not pns: return

    logger.info(f"User {user_id}: Запрос деталей по {len(pns)} заказам...")

    # Проверяем существование пользователя в отдельной сессии
    check_db = SessionLocal()
    try:
        user_exists = check_db.query(User).filter(User.id == user_id).first() is not None
        if not user_exists:
            logger.error(f"User {user_id} not found for enrichment")
            return
    finally:
        check_db.close()

    success_count = 0
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def _enrich_one(pn):
        nonlocal success_count
        async with sem:
            # Открываем СВОЮ сессию на каждую корутину
            db = SessionLocal()
            try:
                res = await enrich_posting_from_ozon(pn, user_id, db)
                if res.get("status") == "ok":
                    success_count += 1
                    db.commit()
                else:
                    db.rollback()
                    logger.warning(f"User {user_id}: Ошибка обогащения {pn}: {res.get('status')} {res.get('detail', '')}")
            except Exception as e:
                db.rollback()
                logger.error(f"User {user_id}: Критическая ошибка при обогащении {pn}: {e}")
            finally:
                db.close()

    # Выполняем асинхронно
    await asyncio.gather(*(_enrich_one(p) for p in pns))

    logger.info(f"User {user_id}: Обогащение завершено. Успешно: {success_count}/{len(pns)}.")

async def initial_backfill_for_user(user: User, db: Session):
    """
    Устойчивый Backfill с чекпоинтами и загрузкой порциями по 30 дней.
    Идет от настоящего в прошлое на 1 год.
    """
    user_id = user.id if hasattr(user, 'id') else user
    bg_db = SessionLocal()
    try:
        sync_status = bg_db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if not sync_status:
            sync_status = SyncStatus(user_id=user_id)
            bg_db.add(sync_status)
            bg_db.commit()
            bg_db.refresh(sync_status)

        if sync_status.backfill_is_complete:
            logger.info(f"User {user_id}: Backfill already completed.")
            return

        now = _get_now_utc()
        start_limit = now - timedelta(days=365)

        # Инициализация границ, если это первый запуск
        if not sync_status.backfill_from:
            sync_status.backfill_from = start_limit
            sync_status.backfill_to = now
            sync_status.backfill_cursor = now # Начинаем с 'now' и идем назад
            sync_status.backfill_started_at = now
            bg_db.commit()

        sync_status.is_syncing = True
        sync_status.sync_started_at = now
        bg_db.commit()

        # Продолжаем с курсора
        current_end = sync_status.backfill_cursor

        while current_end > sync_status.backfill_from:
            # Окно загрузки - 30 дней
            current_start = max(current_end - timedelta(days=30), sync_status.backfill_from)

            sync_status.status_message = f"Backfill: загрузка окна {current_start.strftime('%Y-%m-%d')} — {current_end.strftime('%Y-%m-%d')}"
            bg_db.commit()

            logger.info(f"User {user_id}: {sync_status.status_message}")

            # Цикл пагинации внутри одного окна
            window_offset = 0
            window_limit = 1000 # Увеличили до максимума для скорости
            total_in_window = 0

            while True:
                # Форматируем даты для API без микросекунд
                start_iso = current_start.replace(microsecond=0).isoformat().split('+')[0] + 'Z'
                end_iso = current_end.replace(microsecond=0).isoformat().split('+')[0] + 'Z'

                res = await fetch_and_save_orders_async(
                    start_iso,
                    end_iso,
                    "", window_limit, window_offset, user_id, bg_db
                )

                if res.get("error"):
                    logger.error(f"User {user_id}: Backfill error at window {current_start}-{current_end}: {res['error']}")
                    break

                fetched_count = res.get("fetched", 0)
                total_in_window += fetched_count

                # Обогащение пачки
                if ENRICH_ON_FETCH and res.get("orders"):
                    pns = [o.get("posting_number") for o in res["orders"] if isinstance(o, dict) and valid_posting_number(o.get("posting_number"))]
                    if pns:
                        logger.info(f"User {user_id}: Загружено {total_in_window} заказов в текущем окне...")
                        await run_enrichment_batch(pns, user_id)

                if fetched_count < window_limit:
                    # Больше нет данных в этом окне
                    break

                window_offset += window_limit
                await asyncio.sleep(0.5) # Пауза между страницами

            # Сохраняем прогресс ТОЛЬКО после успешного завершения всего окна
            sync_status.backfill_cursor = current_start
            sync_status.total_records_synced = bg_db.query(Order).filter(Order.user_id == user_id).count()
            bg_db.commit()

            current_end = current_start
            await asyncio.sleep(1) # Небольшая пауза между окнами

        if sync_status.backfill_cursor and sync_status.backfill_cursor <= sync_status.backfill_from:
            sync_status.backfill_is_complete = True
            sync_status.backfill_completed_at = _get_now_utc()
            sync_status.sync_completed_at = _get_now_utc()
            sync_status.status_message = "Backfill completed"

        sync_status.is_syncing = False
        bg_db.commit()

    except Exception as e:
        logger.error(f"User {user_id}: Backfill fatal error: {e}", exc_info=True)
        if sync_status:
            sync_status.is_syncing = False
            sync_status.status_message = f"Backfill error: {str(e)[:50]}"
            bg_db.commit()
    finally:
        bg_db.close()
