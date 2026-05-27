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

logger = logging.getLogger("uvicorn.error")

# Настройки из .env
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))
INITIAL_WINDOW_DAYS = int(os.getenv('INITIAL_WINDOW_DAYS', '365'))
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))


def _get_now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def background_sync_loop(app, interval_seconds: int = 300):
    """
    Фоновый цикл синхронизации для ВСЕХ пользователей.
    """
    logger.info(f"Фоновая синхронизация запущена (интервал={interval_seconds}с)")
    try:
        while True:
            try:
                db = SessionLocal()
                try:
                    users_with_creds = db.query(User).join(OzonCredential).filter(
                        User.is_active == True,
                        OzonCredential.is_active == True
                    ).distinct().all()
                    
                    if not users_with_creds:
                        logger.debug("Нет активных пользователей с Ozon credentials")
                    else:
                        logger.info(f"Синхронизация для {len(users_with_creds)} пользователей")
                        for user in users_with_creds:
                            try:
                                await sync_user_orders(user, db)
                            except Exception as e:
                                logger.error(f"Ошибка синхронизации для user_id={user.id}: {e}")
                finally:
                    db.close()
                
            except Exception as e:
                logger.error(f"Ошибка фоновой синхронизации: {e}")
            
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Фоновая синхронизация остановлена")
        raise


async def sync_user_orders(user: User, db: Session):
    """
    Синхронизирует заказы для одного пользователя.
    """
    try:
        active_cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user.id,
            OzonCredential.is_active == True
        ).first()
        
        if not active_cred:
            return
        
        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)
        
        if not client_id or not api_key:
            logger.error(f"Ошибка расшифровки credentials для user_id={user.id}")
            return
        
        now = _get_now_utc()
        since_dt = now - timedelta(hours=RECENT_WINDOW_HOURS)
        since_iso = since_dt.replace(microsecond=0).isoformat() + 'Z'
        to_iso = now.replace(microsecond=0).isoformat() + 'Z'
        
        filter_dict = {'since': since_iso, 'to': to_iso}
        
        total_saved = 0
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
            
            items = data.get('result', []) or []
            if not items:
                break
            
            for order_data in items:
                saved = save_order_for_user(db, user, order_data)
                if saved:
                    total_saved += 1
                    posting_number = order_data.get('posting_number')
                    if valid_posting_number(posting_number):
                        new_postings.add(posting_number)
            
            if len(items) < limit:
                break
            offset += limit

        if ENRICH_ON_FETCH and (total_saved > 0 or new_postings):
            await run_enrichment_batch(list(new_postings), user.id)

    except Exception as e:
        logger.error(f"Ошибка sync_user_orders для user_id={user.id}: {e}")


def save_order_for_user(db: Session, user: User, order_data: dict) -> bool:
    """
    Сохраняет заказ для пользователя.
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
        logger.error(f"Ошибка save_order_for_user (user_id={user.id}): {e}")
        return False


def fetch_and_save_orders(since: str, to: str, status: str, limit: int, offset: int,
                          with_analytics: bool, with_financial: bool, with_legal: bool,
                          user_id: int, db: Session) -> dict:
    """
    Синхронная функция для вызова из API (обычно через to_thread).
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user_id,
            OzonCredential.is_active == True
        ).first()
        
        if not user or not cred:
            return {"orders": []}
        
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
            # Т.к. эта функция вызывается в потоке, мы можем использовать asyncio.run
            # для вызова асинхронного клиента Ozon
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

        return {"orders": all_orders, "saved": total_saved, "fetched": len(all_orders)}
    except Exception as e:
        logger.error(f"fetch_and_save_orders error user_id={user_id}: {e}")
        return {"orders": []}


async def run_enrichment_batch(posting_numbers: list[str], user_id: int, force_refresh: bool = False) -> int:
    """
    Обогащение пачки постингов.
    """
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def _run_one(pn: str):
        async with sem:
            # Создаем новую сессию для каждого потока/таска чтобы избежать конфликтов
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
    Первичная загрузка.
    """
    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == user.id).first()
    if not sync_status:
        sync_status = SyncStatus(user_id=user.id)
        db.add(sync_status)

    sync_status.is_syncing = True
    sync_status.status_message = "Идет загрузка данных..."
    sync_status.sync_started_at = _get_now_utc()
    db.commit()
    
    try:
        now = _get_now_utc()
        start_dt = now - timedelta(days=INITIAL_WINDOW_DAYS)
        window_start = start_dt
        total_saved = 0

        while window_start < now:
            window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), now)
            since_iso = window_start.replace(microsecond=0).isoformat() + 'Z'
            to_iso = window_end.replace(microsecond=0).isoformat() + 'Z'

            result = await asyncio.to_thread(
                fetch_and_save_orders,
                since_iso, to_iso, "", 50, 0, True, True, False, user.id, db
            )

            orders = result.get("orders") or []
            total_saved += result.get("saved") or 0

            if ENRICH_ON_FETCH and orders:
                pns = [o.get("posting_number") for o in orders if valid_posting_number(o.get("posting_number"))]
                await run_enrichment_batch(pns, user.id)

            window_start = window_end + timedelta(seconds=1)
        
        sync_status.is_syncing = False
        sync_status.status_message = "completed"
        sync_status.sync_completed_at = _get_now_utc()
        sync_status.total_records_synced = total_saved
        db.commit()
        return {"saved": total_saved}

    except Exception as e:
        logger.error(f"Initial sync failed for user {user.id}: {e}")
        sync_status.is_syncing = False
        sync_status.status_message = f"error: {str(e)[:50]}"
        db.commit()
        raise
