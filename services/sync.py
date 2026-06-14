"""
Модуль синхронизации данных с Ozon API.
Содержит логику фонового обновления заказов, первичной загрузки истории (backfill)
и функции сохранения данных в базу.
"""

import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from db.database import User, Order, OrderPosting, OrderProduct, OzonCredential, SessionLocal, SyncStatus
from services.enrichment import enrich_posting_from_ozon
from services.ozon import ozon_fbo_list_async
from utils.encryption import decrypt_credential
from utils.common import valid_posting_number
from utils.logging_config import log_user_event

logger = logging.getLogger("OzonAPIHub")

# Настройки из .env
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))  # Глубина обычной проверки (последние 48 часов)
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes') # Подгружать ли детальные данные сразу
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))     # Количество параллельных запросов на обогащение
INITIAL_WINDOW_DAYS = int(os.getenv('INITIAL_WINDOW_DAYS', '365')) # Глубина первой загрузки (1 год)
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))  # Размер порции данных при загрузке истории (30 дней)


def _get_now_utc():
    """Возвращает текущее время UTC без TZ."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def background_sync_loop(app, interval_seconds: int = 300):
    """
    Бесконечный цикл для автоматической синхронизации всех активных пользователей.
    Запускается при старте приложения.
    """
    logger.info(f"Фоновая синхронизация запущена (интервал={interval_seconds}с)")
    try:
        while True:
            try:
                db = SessionLocal()
                try:
                    # Находим всех пользователей, у которых есть активные API ключи
                    users_with_creds = db.query(User).join(OzonCredential).filter(
                        User.is_active == True,
                        OzonCredential.is_active == True
                    ).distinct().all()
                    
                    if not users_with_creds:
                        logger.debug("Нет активных пользователей с Ozon credentials")
                    else:
                        logger.info(f"Начало цикла синхронизации для {len(users_with_creds)} пользователей")
                        for user in users_with_creds:
                            try:
                                # Синхронизируем заказы для каждого пользователя по очереди
                                await sync_user_orders(user, db)
                            except Exception as e:
                                error_msg = f"Ошибка синхронизации для user_id={user.id}: {e}"
                                logger.error(error_msg)
                                log_user_event(user.id, error_msg, "error")
                finally:
                    db.close()
                
            except Exception as e:
                logger.error(f"Критическая ошибка фоновой синхронизации: {e}")
            
            # Ждем до следующего цикла
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Фоновая синхронизация остановлена")
        raise


async def sync_user_orders(user: User, db: Session):
    """
    Синхронизирует заказы для ОДНОГО пользователя (проверяет только недавнее окно времени).
    """
    try:
        active_cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user.id,
            OzonCredential.is_active == True
        ).first()
        
        if not active_cred:
            return

        log_user_event(user.id, f"Запуск плановой синхронизации (окно {RECENT_WINDOW_HOURS}ч)")

        # Дешифруем ключи доступа
        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)
        
        if not client_id or not api_key:
            error_msg = "Ошибка расшифровки credentials. Синхронизация невозможна."
            logger.error(f"User {user.id}: {error_msg}")
            log_user_event(user.id, error_msg, "error")
            return
        
        # Определяем временной диапазон для проверки обновлений
        now = _get_now_utc()
        since_dt = now - timedelta(hours=RECENT_WINDOW_HOURS)
        since_iso = since_dt.replace(microsecond=0).isoformat() + 'Z'
        to_iso = now.replace(microsecond=0).isoformat() + 'Z'
        
        filter_dict = {'since': since_iso, 'to': to_iso}
        
        total_saved = 0
        total_fetched = 0
        new_postings: set[str] = set()
        offset = 0
        limit = 50
        
        # Пагинация: качаем заказы порциями по 50 штук
        while True:
            data = await ozon_fbo_list_async(
                client_id=client_id,
                api_key=api_key,
                filter_dict=filter_dict,
                limit=limit,
                offset=offset,
                with_flags={"analytics_data": True, "financial_data": True}
            )
            
            items = data.get('result', []) or []
            if not items:
                break
            
            total_fetched += len(items)
            for order_data in items:
                try:
                    # Сохраняем в таблицу Orders (сырые данные)
                    saved = save_order_for_user(db, user, order_data)
                    if saved:
                        total_saved += 1
                        posting_number = order_data.get('posting_number')
                        if valid_posting_number(posting_number):
                            new_postings.add(posting_number)
                except Exception as e:
                    log_user_event(user.id, f"Ошибка сохранения заказа {order_data.get('posting_number')}: {e}", "error")
            
            if len(items) < limit:
                break
            offset += limit

        log_user_event(user.id, f"Синхронизация завершена. Получено: {total_fetched}, Новых: {total_saved}")

        # Если включено обогащение, запускаем подгрузку деталей для новых заказов
        if ENRICH_ON_FETCH and new_postings:
            log_user_event(user.id, f"Запуск обогащения для {len(new_postings)} новых постингов")
            await run_enrichment_batch(list(new_postings), user.id)

    except Exception as e:
        error_msg = f"Ошибка sync_user_orders: {e}"
        logger.error(f"User {user.id}: {error_msg}")
        log_user_event(user.id, error_msg, "error")


def save_order_for_user(db: Session, user: User, order_data: dict) -> bool:
    """
    Сохраняет или обновляет запись заказа в таблице Orders.
    Возвращает True, если это был новый заказ, и False, если обновление старого.
    """
    posting_number = order_data.get('posting_number')
    if not posting_number:
        return False
    
    try:
        order_id = order_data.get('order_id')
        status = order_data.get('status')
        created_at = order_data.get('created_at')

        # Проверяем наличие заказа в базе
        existing = db.query(Order).filter(
            Order.user_id == user.id,
            Order.posting_number == posting_number
        ).first()

        if existing:
            # Обновляем существующий (если сменился статус или данные)
            existing.order_id = order_id
            existing.status = status
            existing.updated_at = created_at
            existing.data = order_data
            db.commit()
            return False
        else:
            # Создаем новый
            new_order = Order(
                user_id=user.id,
                order_id=order_id,
                posting_number=posting_number,
                status=status,
                created_at=created_at,
                updated_at=created_at,
                data=order_data
            )
            db.add(new_order)
            db.commit()
            return True

    except Exception as e:
        db.rollback()
        raise e


def fetch_and_save_orders(since: str, to: str, status: str, limit: int, offset: int,
                          with_analytics: bool, with_financial: bool, with_legal: bool,
                          user_id: int, db: Session) -> dict:
    """
    Синхронная обертка над API Ozon.
    Используется для ручного запроса заказов за конкретный период.
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user_id,
            OzonCredential.is_active == True
        ).first()
        
        if not user or not cred:
            return {"orders": []}

        log_user_event(user_id, f"Ручной запрос заказов: {since} -> {to}")

        client_id = decrypt_credential(cred.client_id_encrypted)
        api_key = decrypt_credential(cred.api_key_encrypted)
        
        filter_dict = {}
        if since: filter_dict["since"] = since
        if to: filter_dict["to"] = to
        if status: filter_dict["status"] = status
        
        total_saved = 0
        all_orders = []
        current_offset = offset

        while True:
            # Выполняем асинхронный запрос в синхронном контексте (используется asyncio.run)
            response = asyncio.run(ozon_fbo_list_async(
                client_id=client_id,
                api_key=api_key,
                filter_dict=filter_dict,
                limit=limit,
                offset=current_offset,
                with_flags={
                    "analytics_data": with_analytics,
                    "financial_data": with_financial,
                    "legal_info": with_legal
                }
            ))

            items = response.get("result", []) if isinstance(response, dict) else []
            if not items:
                break

            for order_data in items:
                saved = save_order_for_user(db, user, order_data)
                if saved:
                    total_saved += 1
                all_orders.append(order_data)

            if len(items) < limit:
                break
            current_offset += limit

        log_user_event(user_id, f"Результат ручного запроса: сохранено {total_saved}")
        return {"orders": all_orders, "saved": total_saved, "fetched": len(all_orders)}
    except Exception as e:
        error_msg = f"Ошибка fetch_and_save_orders: {e}"
        logger.error(f"User {user_id}: {error_msg}")
        log_user_event(user_id, error_msg, "error")
        return {"orders": []}


async def run_enrichment_batch(posting_numbers: list[str], user_id: int, force_refresh: bool = False) -> int:
    """
    Запускает процесс обогащения (подгрузки деталей) для списка заказов.
    Использует семафор для ограничения количества одновременных запросов к API.
    """
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def _run_one(pn: str):
        async with sem:
            async_db = SessionLocal() # Каждой задаче - своя сессия БД
            try:
                # Если не форсируем обновление, проверяем, нет ли уже товаров этого заказа в базе
                if not force_refresh:
                    exists = async_db.query(OrderProduct).filter(
                        OrderProduct.posting_number == pn,
                        OrderProduct.user_id == user_id
                    ).first()
                    if exists: return
                
                user = async_db.query(User).filter(User.id == user_id).first()
                if user:
                    await enrich_posting_from_ozon(pn, user, async_db)
            finally:
                async_db.close()

    # Фильтруем пустые номера
    targets = [pn for pn in posting_numbers if valid_posting_number(pn)]
    if not targets: return 0

    # Запускаем всё параллельно
    await asyncio.gather(*(_run_one(pn) for pn in targets), return_exceptions=True)
    return len(targets)


async def initial_backfill_for_user(user: User, db: Session) -> dict:
    """
    Процесс ПЕРВИЧНОЙ загрузки всей истории заказов пользователя (например, за последний год).
    Разбивает большой период на маленькие окна (по 30 дней) для стабильности.
    """
    # Безопасное получение ID (даже если объект отсоединен от сессии)
    try:
        user_id = user if isinstance(user, int) else user.__dict__.get('id')
    except Exception as e:
        logger.error(f"[BACKFILL] Фатальная ошибка извлечения user_id: {e}")
        return {"error": "no user_id"}
    
    logger.info(f"=== [BACKFILL] ЗАПУСК ЗАДАЧИ ДЛЯ ПОЛЬЗОВАТЕЛЯ {user_id} ===")
    
    if not user_id:
        return {"error": "no user_id"}

    # Создаем независимую сессию для долгой фоновой задачи
    from db.database import SessionLocal
    bg_db = SessionLocal()

    try:
        # Инициализируем статус синхронизации в БД
        sync_status = bg_db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if not sync_status:
            sync_status = SyncStatus(user_id=user_id)
            bg_db.add(sync_status)

        sync_status.is_syncing = True
        sync_status.status_message = "Подготовка базы к загрузке..."
        sync_status.sync_started_at = _get_now_utc()
        bg_db.commit()

        log_user_event(user_id, f"Начало первичной загрузки за {INITIAL_WINDOW_DAYS} дней")

        now = _get_now_utc()
        window_start = now - timedelta(days=INITIAL_WINDOW_DAYS)
        total_saved = 0

        # Цикл по временным окнам
        while window_start < now:
            window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), now)
            since_iso = window_start.replace(microsecond=0).isoformat() + 'Z'
            to_iso = window_end.replace(microsecond=0).isoformat() + 'Z'

            # Обновляем прогресс для фронтенда
            sync_status.status_message = f"Загрузка: {window_start.strftime('%d.%m.%Y')} - {window_end.strftime('%d.%m.%Y')}..."
            bg_db.commit()
            
            logger.info(f"[BACKFILL] Текущий прогресс: {sync_status.status_message}")
            await asyncio.sleep(0.5) # Небольшая пауза для снижения нагрузки

            # Выполняем запрос заказов (в отдельном потоке, чтобы не блокировать цикл событий)
            result = await asyncio.to_thread(
                fetch_and_save_orders,
                since_iso, to_iso, "", 50, 0, True, True, False, user_id, bg_db
            )

            orders = result.get("orders") or []
            total_saved += result.get("saved") or 0

            # Обогащаем (подгружаем комиссии) для каждого окна сразу
            if ENRICH_ON_FETCH and orders:
                pns = [o.get("posting_number") for o in orders if valid_posting_number(o.get("posting_number"))]
                if pns:
                    sync_status.status_message = f"Загрузка комиссий для {len(pns)} заказов..."
                    bg_db.commit()
                    await run_enrichment_batch(pns, user_id)

            sync_status.total_records_synced = total_saved
            bg_db.commit()

            window_start = window_end + timedelta(seconds=1)
        
        # Завершение
        sync_status.is_syncing = False
        sync_status.status_message = "completed"
        sync_status.sync_completed_at = _get_now_utc()
        bg_db.commit()

        log_user_event(user_id, f"Первичная загрузка завершена успешно. Всего: {total_saved}")
        return {"saved": total_saved}

    except Exception as e:
        # Обработка ошибок синхронизации
        error_msg = f"Критическая ошибка первичной загрузки: {e}"
        logger.error(f"[BACKFILL] Initial sync failed for user {user_id}: {e}")
        try:
            err_sync = bg_db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
            if err_sync:
                err_sync.is_syncing = False
                err_sync.status_message = f"error: {str(e)[:50]}"
                bg_db.commit()
        except: pass
        raise
    finally:
        bg_db.close()
