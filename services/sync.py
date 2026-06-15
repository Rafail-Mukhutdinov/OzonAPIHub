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
from sqlalchemy import desc
from db.database import User, Order, OrderPosting, OrderProduct, OzonCredential, SessionLocal, SyncStatus
from services.enrichment import enrich_posting_from_ozon
from services.ozon import ozon_fbo_list_async
from utils.encryption import decrypt_credential
from utils.common import valid_posting_number
from utils.logging_config import log_user_event

logger = logging.getLogger("OzonAPIHub")

# Настройки из .env (сокращаем стандартное окно, так как Gap Filling подстрахует)
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '24'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))
INITIAL_WINDOW_DAYS = int(os.getenv('INITIAL_WINDOW_DAYS', '365'))
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))


def _get_now_utc():
    """Возвращает текущее время UTC без TZ."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def sync_user_orders(user: User, db: Session) -> bool:
    """
    Синхронизирует заказы для ОДНОГО пользователя.
    Возвращает True, если были найдены новые заказы или изменения.
    """
    try:
        active_cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user.id,
            OzonCredential.is_active == True
        ).first()
        
        if not active_cred:
            return False

        # --- Smart Gap Filling LOGIC ---
        now = _get_now_utc()
        default_since = now - timedelta(hours=RECENT_WINDOW_HOURS)

        last_order = db.query(Order).filter(Order.user_id == user.id).order_by(desc(Order.created_at)).first()

        since_dt = default_since
        is_gap_fill = False

        if last_order and last_order.created_at:
            try:
                last_dt = datetime.fromisoformat(last_order.created_at.replace('Z', ''))
                if last_dt < default_since:
                    since_dt = last_dt - timedelta(minutes=30)
                    is_gap_fill = True
                    logger.info(f"User {user.id}: Обнаружен пробел в данных. Последний заказ: {last_dt}. Расширяем окно.")
            except Exception as e:
                logger.warning(f"User {user.id}: Ошибка парсинга даты последнего заказа: {e}")

        since_iso = since_dt.replace(microsecond=0).isoformat() + 'Z'
        to_iso = now.replace(microsecond=0).isoformat() + 'Z'

        log_msg = f"Запуск синхронизации ({'GAP FILL' if is_gap_fill else 'ПЛАНОВАЯ'}). Окно: {since_iso} -> {to_iso}"
        log_user_event(user.id, log_msg)

        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)
        
        if not client_id or not api_key:
            return False

        filter_dict = {'since': since_iso, 'to': to_iso}
        
        total_saved = 0
        total_fetched = 0
        new_postings: set[str] = set()
        offset = 0
        limit = 50
        
        while True:
            data = await ozon_fbo_list_async(
                client_id=client_id,
                api_key=api_key,
                filter_dict=filter_dict,
                limit=limit,
                offset=offset,
                with_flags={"analytics_data": True, "financial_data": True}
            )
            
            items = []
            if isinstance(data, dict):
                result_obj = data.get("result")
                if isinstance(result_obj, dict):
                    items = result_obj.get("postings", [])
                elif isinstance(result_obj, list):
                    items = result_obj
            elif isinstance(data, list):
                items = data

            if not items:
                break
            
            total_fetched += len(items)
            for order_data in items:
                try:
                    if not isinstance(order_data, dict): continue
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

        if total_fetched > 0:
            log_user_event(user.id, f"Синхронизация завершена. Получено: {total_fetched}, Новых: {total_saved}")

        if ENRICH_ON_FETCH and new_postings:
            await run_enrichment_batch(list(new_postings), user.id)

        return total_saved > 0

    except Exception as e:
        error_msg = f"Ошибка sync_user_orders: {e}"
        logger.error(f"User {user.id}: {error_msg}")
        return False


def save_order_for_user(db: Session, user: User, order_data: dict) -> bool:
    """
    Сохраняет или обновляет запись заказа в таблице Orders.
    """
    posting_number = order_data.get('posting_number')
    if not posting_number:
        return False
    
    try:
        order_id = order_data.get('order_id')
        status = order_data.get('status')
        created_at = order_data.get('created_at')

        existing = db.query(Order).filter(
            Order.user_id == user.id,
            Order.posting_number == posting_number
        ).first()

        if existing:
            existing.order_id = order_id
            existing.status = status
            existing.updated_at = created_at
            existing.data = order_data
            db.commit()
            return False
        else:
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


async def fetch_and_save_orders_async(since: str, to: str, status: str, limit: int, offset: int,
                                user_id: int, db: Session) -> dict:
    """
    Асинхронная версия получения и сохранения заказов.
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user_id,
            OzonCredential.is_active == True
        ).first()
        
        if not user or not cred:
            return {"orders": [], "saved": 0, "fetched": 0}

        client_id = decrypt_credential(cred.client_id_encrypted)
        api_key = decrypt_credential(cred.api_key_encrypted)
        
        filter_dict = {}
        if since: filter_dict["since"] = since
        if to: filter_dict["to"] = to
        if status: filter_dict["status"] = status
        
        total_saved = 0
        all_postings = []
        current_offset = offset

        while True:
            response = await ozon_fbo_list_async(
                client_id=client_id,
                api_key=api_key,
                filter_dict=filter_dict,
                limit=limit,
                offset=current_offset
            )

            items = []
            if isinstance(response, dict):
                result_obj = response.get("result")
                if isinstance(result_obj, dict):
                    items = result_obj.get("postings", [])
                elif isinstance(result_obj, list):
                    items = result_obj
            elif isinstance(response, list):
                items = response

            if not items:
                break

            for order_data in items:
                if not isinstance(order_data, dict): continue
                saved = save_order_for_user(db, user, order_data)
                if saved:
                    total_saved += 1
                all_postings.append(order_data)

            if len(items) < limit:
                break
            current_offset += limit

        return {"orders": all_postings, "saved": total_saved, "fetched": len(all_postings)}
    except Exception as e:
        logger.error(f"User {user_id}: fetch_and_save_orders_async error: {e}")
        return {"orders": [], "saved": 0, "fetched": 0, "error": str(e)}


async def run_enrichment_batch(posting_numbers: list[str], user_id: int, force_refresh: bool = False) -> int:
    """
    Запускает процесс обогащения (подгрузки деталей) для списка заказов.
    """
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def _run_one(pn: str):
        async with sem:
            async_db = SessionLocal()
            try:
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

    targets = [pn for pn in posting_numbers if valid_posting_number(pn)]
    if not targets: return 0

    await asyncio.gather(*(_run_one(pn) for pn in targets), return_exceptions=True)
    return len(targets)


async def initial_backfill_for_user(user: User, db: Session) -> dict:
    """
    Процесс ПЕРВИЧНОЙ загрузки всей истории заказов пользователя.
    """
    user_id = user if isinstance(user, int) else user.id
    logger.info(f"=== [BACKFILL] ЗАПУСК ЗАДАЧИ ДЛЯ ПОЛЬЗОВАТЕЛЯ {user_id} ===")
    
    bg_db = SessionLocal()

    try:
        sync_status = bg_db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if not sync_status:
            sync_status = SyncStatus(user_id=user_id)
            bg_db.add(sync_status)

        sync_status.is_syncing = True
        sync_status.status_message = "Подготовка базы к загрузке..."
        sync_status.sync_started_at = _get_now_utc()
        bg_db.commit()

        now = _get_now_utc()
        window_start = now - timedelta(days=INITIAL_WINDOW_DAYS)
        total_saved = 0

        while window_start < now:
            window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), now)
            since_iso = window_start.replace(microsecond=0).isoformat() + 'Z'
            to_iso = window_end.replace(microsecond=0).isoformat() + 'Z'

            sync_status.status_message = f"Загрузка: {window_start.strftime('%d.%m.%Y')} - {window_end.strftime('%d.%m.%Y')}..."
            bg_db.commit()
            
            result = await fetch_and_save_orders_async(
                since_iso, to_iso, "", 50, 0, user_id, bg_db
            )

            orders = result.get("orders") or []
            total_saved += result.get("saved") or 0

            if ENRICH_ON_FETCH and orders:
                pns = [o.get("posting_number") for o in orders if valid_posting_number(o.get("posting_number"))]
                if pns:
                    await run_enrichment_batch(pns, user_id)

            sync_status.total_records_synced = total_saved
            bg_db.commit()

            window_start = window_end + timedelta(seconds=1)
        
        sync_status.is_syncing = False
        sync_status.status_message = "completed"
        sync_status.sync_completed_at = _get_now_utc()
        bg_db.commit()

        log_user_event(user_id, f"Первичная загрузка завершена успешно. Всего: {total_saved}")
        return {"saved": total_saved}

    except Exception as e:
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
