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
from db.database import User, Order, OrderPosting, OrderProduct, OzonCredential, SessionLocal, SyncStatus, Cost, OzonAccrual
from services.enrichment import enrich_posting_from_ozon, enrich_accruals_from_ozon
from services.ozon import ozon_fbo_list_async, ozon_transaction_list_async, ozon_accruals_by_day_async
from utils.encryption import decrypt_credential
from utils.common import valid_posting_number, to_msk, to_msk_date, parse_ozon_datetime, get_now_utc
from utils.logging_config import log_user_event

logger = logging.getLogger("OzonAPIHub")

# Настройки из .env
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '24'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '2')) # Берем из env, по умолчанию 2

def _get_now_utc():
    return get_now_utc()

def get_latest_order_datetime(db: Session, user_id: int) -> Union[datetime, None]:
    """
    Находит дату последнего заказа пользователя, используя нативную агрегацию SQL.
    """
    raw_max = db.query(func.max(Order.created_at)).filter(
        Order.user_id == user_id
    ).scalar()

    posting_max = db.query(func.max(OrderPosting.created_at)).filter(
        OrderPosting.user_id == user_id
    ).scalar()

    values = [v for v in [raw_max, posting_max] if v is not None]
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

        # ЗАЩИТА: Ozon API возвращает 400, если since > to. 
        # Такое бывает при рассинхроне времени или если последний заказ из "будущего".
        if since_dt >= now:
            since_dt = now - timedelta(seconds=10)

        # Убеждаемся, что окно не слишком большое для регулярной синхронизации
        if since_dt < now - timedelta(days=60):
            since_dt = now - timedelta(days=60)

        # Не добавляем +1 секунду, чтобы не терять заказы на стыке
        since_iso = since_dt.replace(microsecond=0).isoformat().split('+')[0] + 'Z'
        to_iso = now.replace(microsecond=0).isoformat().split('+')[0] + 'Z'

        # Обновляем время последней проверки для адаптивного планировщика
        status = db.query(SyncStatus).filter(SyncStatus.user_id == user.id).first()

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

                # Используем вложенную транзакцию (SAVEPOINT), чтобы ошибка в одном заказе
                # не отменяла всю пачку успешно загруженных заказов на странице.
                try:
                    with db.begin_nested():
                        # Сохраняем в сессию (коммит сделаем ниже пачкой)
                        is_active_change = save_order_for_user(db, user, o)

                        # Добавляем в очередь на обогащение если:
                        # - это новый заказ/изменение статуса
                        # - ИЛИ заказа нет в нормализованной таблице (был пропущен или ошибка)
                        if is_active_change or (pn not in existing_norm_pns):
                            total_saved += 1
                            if valid_posting_number(pn):
                                new_pns.add(pn)
                except Exception as e:
                    logger.error(f"User {user.id}: Пропуск заказа {pn} из-за ошибки: {e}")
                    # Вложенная транзакция автоматически откатится здесь

            # BATCH COMMIT: Сохраняем всю страницу (обычно 50 заказов) за одну транзакцию
            db.commit()

            if len(items) < limit: break
            offset += limit

        if total_saved > 0:
            log_user_event(user.id, f"Найдено новых заказов: {total_saved}. Запуск обогащения...")
            if ENRICH_ON_FETCH:
                await run_enrichment_batch(list(new_pns), user.id)

        # Запускаем синхронизацию транзакций (расходы: реклама, хранение)
        await sync_ozon_transactions(user.id, db)
        
        # Запускаем НОВУЮ синхронизацию детальных начислений (accruals v1)
        # Синхронизируем сегодня и вчера для надежности
        today_s = now.strftime("%Y-%m-%d")
        yesterday_s = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        
        await enrich_accruals_from_ozon(user.id, today_s, db)
        await enrich_accruals_from_ozon(user.id, yesterday_s, db)

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

        # Конвертация даты в объект datetime для БД
        raw_created_at = order_data.get('created_at')
        dt_created = parse_ozon_datetime(raw_created_at)
        if dt_created:
            dt_created = dt_created.astimezone(timezone.utc).replace(tzinfo=None)

        if existing:
            if existing.status != status:
                existing.status = status
                existing.updated_at = dt_created
                return True # Изменение статуса тоже считаем активностью
            return False
        new_order = Order(
            user_id=user_id,
            order_id=order_data.get('order_id'),
            posting_number=posting_number, status=status,
            created_at=dt_created,
            updated_at=dt_created,
            data=order_data
        )
        db.add(new_order)
        return True
    except Exception as e:
        logger.error(f"Error saving order {posting_number}: {e}")
        # ВАЖНО: Мы больше не делаем здесь db.rollback(), так как это ломает всю
        # внешнюю транзакцию. Ошибку должен обработать вызывающий код через begin_nested().
        raise

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
            pn = o.get('posting_number', 'unknown')
            try:
                with db.begin_nested():
                    if save_order_for_user(db, user, o):
                        saved += 1
                valid_orders.append(o)
            except Exception as e:
                logger.error(f"Error saving order {pn} in fetch_and_save: {e}")

        # BATCH COMMIT: Сохраняем все найденные заказы разом
        db.commit()

        return {"saved": saved, "fetched": len(items), "orders": valid_orders}
    except Exception as e:
        logger.error(f"fetch_and_save_orders_async error: {e}")
        return {"saved": 0, "fetched": 0, "error": str(e), "orders": []}

async def run_enrichment_batch(pns: list[str], user_id: int):
    """
    Массовое обогащение.
    Оптимизировано: ключи Ozon получаются один раз, сессия на каждый заказ своя.
    """
    if not pns: return

    logger.info(f"User {user_id}: Запрос деталей по {len(pns)} заказам...")

    # Получаем ключи ОДИН раз на всю пачку
    check_db = SessionLocal()
    client_id = None
    api_key = None
    try:
        cred = check_db.query(OzonCredential).filter(
            OzonCredential.user_id == user_id,
            OzonCredential.is_active == True
        ).first()
        if not cred:
            logger.error(f"Credentials not found for user {user_id}")
            return

        client_id = decrypt_credential(cred.client_id_encrypted)
        api_key = decrypt_credential(cred.api_key_encrypted)
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
                # Передаем уже готовые ключи, чтобы не делать лишних SELECT к БД
                res = await enrich_posting_from_ozon(
                    posting_number=pn,
                    user_id=user_id,
                    db=db,
                    client_id=client_id,
                    api_key=api_key
                )
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

async def sync_ozon_transactions(user_id: int, db: Session, days_back: int = 30):
    """
    Синхронизирует транзакции Ozon (реклама, хранение и т.д.) в таблицу Cost.
    Позволяет получить точные данные по расходам, как в отчетах Ozon.
    """
    try:
        active_cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user_id,
            OzonCredential.is_active == True
        ).first()

        if not active_cred: return 0

        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)

        now = get_now_utc()
        since_dt = now - timedelta(days=days_back)

        # Формат для транзакций Ozon: 2021-11-01T00:00:00Z
        from_iso = since_dt.replace(microsecond=0).isoformat() + 'Z'
        to_iso = now.replace(microsecond=0).isoformat() + 'Z'

        page = 1
        total_synced = 0

        while page <= 5: # Ограничим 5 страницами для начала
            data = await ozon_transaction_list_async(client_id, api_key, from_iso, to_iso, page=page)
            result = data.get("result", {})
            operations = result.get("operations", [])

            if not operations:
                break

            for op in operations:
                amount = float(op.get("amount") or 0)

                # Нас интересуют только расходы (отрицательные суммы)
                if amount >= 0:
                    continue

                op_id = str(op.get("operation_id"))
                op_date_raw = op.get("operation_date")
                dt_op = parse_ozon_datetime(op_date_raw)
                if dt_op:
                    dt_op = dt_op.replace(tzinfo=None)

                # Проверяем дубликат по ID операции в поле notes
                check_tag = f"[ID:{op_id}]"
                existing = db.query(Cost).filter(
                    Cost.user_id == user_id,
                    Cost.notes.contains(check_tag)
                ).first()

                if not existing:
                    # Определяем категорию расхода
                    category = "other"
                    type_name = op.get("operation_type_name", "").lower()

                    # Проверяем вложенные услуги
                    services = op.get("services", [])
                    service_names = " ".join([s.get("name", "").lower() for s in services])

                    if "реклам" in type_name or "реклам" in service_names or "promotion" in service_names:
                        category = "advertising"
                    elif "хранен" in type_name or "storage" in service_names or "inventory" in service_names:
                        category = "storage"
                    elif "логистик" in type_name or "доставк" in type_name or "delivery" in type_name:
                        category = "logistics"

                    # Собираем доп. инфо
                    notes = f"{op.get('operation_type_name')} {check_tag}"
                    if services:
                        notes += " | Услуги: " + ", ".join([f"{s.get('name')}: {s.get('price')}" for s in services])

                    new_cost = Cost(
                        user_id=user_id,
                        type=category,
                        amount=int(abs(amount)),
                        date=dt_op,
                        notes=notes
                    )
                    db.add(new_cost)
                    total_synced += 1

            db.commit()
            if len(operations) < 1000:
                break
            page += 1
            await asyncio.sleep(0.1)

        return total_synced
    except Exception as e:
        logger.error(f"Error syncing transactions for user {user_id}: {e}")
        return 0

async def sync_range_for_user(user_id: int, start_dt: datetime, end_dt: datetime, db: Session):
    """
    Синхронизирует заказы и начисления за конкретный период.
    """
    # Гарантируем, что даты без часового пояса для сравнения
    start_dt = start_dt.replace(tzinfo=None)
    end_dt = end_dt.replace(tzinfo=None)

    # Проверка наличия активных ключей (Рекомендация №1)
    cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
    if not cred:
        logger.error(f"User {user_id}: Range sync aborted - No active Ozon Credentials found!")
        return

    logger.info(f"User {user_id}: Starting manual range sync: {start_dt} - {end_dt}")

    # Обновляем статус синхронизации, чтобы UI показывал прогресс
    # и адаптивный планировщик не запускал параллельную синхронизацию
    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
    if not sync_status:
        sync_status = SyncStatus(user_id=user_id)
        db.add(sync_status)
    sync_status.is_syncing = True
    sync_status.status_message = f"Range sync: {start_dt.strftime('%Y-%m-%d')} — {end_dt.strftime('%Y-%m-%d')}"
    sync_status.sync_started_at = _get_now_utc()
    db.commit()

    try:
        # Загрузка заказов
        current_end = end_dt
        while current_end > start_dt:
            current_start = current_end - timedelta(days=30)
            if current_start < start_dt:
                current_start = start_dt

            start_iso = current_start.replace(microsecond=0).isoformat() + 'Z'
            end_iso = current_end.replace(microsecond=0).isoformat() + 'Z'

            res = await fetch_and_save_orders_async(
                start_iso, end_iso, "", 1000, 0, user_id, db
            )

            if res.get("orders"):
                pns = [o.get("posting_number") for o in res["orders"] if isinstance(o, dict) and valid_posting_number(o.get("posting_number"))]
                if pns:
                    await run_enrichment_batch(pns, user_id)

            # Загрузка начислений
            acc_current = current_end
            while acc_current >= current_start:
                acc_date_s = acc_current.strftime("%Y-%m-%d")
                await enrich_accruals_from_ozon(user_id, acc_date_s, db)
                acc_current -= timedelta(days=1)

            current_end = current_start
            await asyncio.sleep(0.5)

        logger.info(f"User {user_id}: Manual range sync completed.")
    finally:
        # Сбрасываем флаг синхронизации в любом случае (даже при ошибке)
        db.refresh(sync_status)
        sync_status.is_syncing = False
        sync_status.status_message = "ok"
        sync_status.sync_completed_at = _get_now_utc()
        sync_status.updated_at = _get_now_utc()
        db.commit()


async def initial_backfill_for_user(user: User, db: Session):
    """
    Устойчивый Backfill с чекпоинтами и загрузкой порциями по 30 дней.
    Идет от настоящего в прошлое на 1 год.
    """
    user_id = user.id if hasattr(user, 'id') else user

    # ПРОВЕРКА КЛЮЧЕЙ ПЕРЕД НАЧАЛОМ
    cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
    if not cred:
        logger.error(f"User {user_id}: Backfill aborted - No active Ozon Credentials found!")
        status = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if status:
            status.is_syncing = False
            status.status_message = "Ошибка: не настроены API ключи Ozon"
            db.commit()
        return

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

        # Убираем проверку if sync_status.is_syncing, так как она блокирует запуск задачи,
        # которая сама же и установила этот флаг через API.

        now = _get_now_utc()
        logger.info(f"User {user_id}: Starting/Resuming backfill process at {now}")

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
        current_end = sync_status.backfill_cursor or now

        while current_end > start_limit:
            # Окно загрузки - 30 дней
            current_start = current_end - timedelta(days=30)
            if current_start < start_limit:
                current_start = start_limit

            sync_status.status_message = f"Backfill: загрузка окна {current_start.strftime('%Y-%m-%d')} — {current_end.strftime('%Y-%m-%d')}"
            sync_status.is_syncing = True
            bg_db.commit()

            logger.info(f"User {user_id}: {sync_status.status_message}")

            # Цикл пагинации внутри одного окна
            window_offset = 0
            window_limit = 1000 # Увеличили до максимума для скорости
            total_in_window = 0
            empty_pages_count = 0

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
                        logger.info(f"User {user_id}: Загружено {total_in_window} заказов в текущем окне. Запуск обогащения...")
                        # Разбиваем на подпачки по 50 для стабильности, если пришло 1000
                        for i in range(0, len(pns), 50):
                            await run_enrichment_batch(pns[i:i+50], user_id)

                if fetched_count == 0:
                    empty_pages_count += 1
                else:
                    empty_pages_count = 0

                if fetched_count < window_limit or empty_pages_count >= 3:
                    break

                window_offset += window_limit
                await asyncio.sleep(0.3)

            # --- НОВОЕ: Загрузка транзакций (accruals) за это же окно ---
            logger.info(f"User {user_id}: Загрузка транзакций за период {current_start.date()} - {current_end.date()}")
            acc_current = current_end
            while acc_current >= current_start:
                acc_date_s = acc_current.strftime("%Y-%m-%d")
                await enrich_accruals_from_ozon(user_id, acc_date_s, bg_db)
                acc_current -= timedelta(days=1)
                await asyncio.sleep(0.2) # Небольшая пауза, чтобы не спамить API

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

    except (Exception, asyncio.CancelledError) as e:
        logger.error(f"User {user_id}: Backfill interrupted or failed: {e}")
        # Пытаемся сохранить статус ошибки, если это возможно
        try:
            # Нам нужна новая сессия, так как старая могла быть прервана
            fail_db = SessionLocal()
            try:
                st = fail_db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
                if st:
                    st.is_syncing = False
                    st.status_message = f"Interrupted: {str(e)[:50]}"
                    fail_db.commit()
            finally:
                fail_db.close()
        except:
            pass
        if isinstance(e, asyncio.CancelledError):
            raise
    finally:
        bg_db.close()
