import os
import logging
logger = logging.getLogger("uvicorn.error")
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from db.database import User, Order, OrderPosting, OrderProduct, OzonCredential, SessionLocal, SyncStatus
from services.enrichment import enrich_posting_from_ozon
from services.ozon import ozon_fbo_list_async
from utils.encryption import decrypt_credential
from utils.common import valid_posting_number

# Настройки из .env
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))
INITIAL_WINDOW_DAYS = int(os.getenv('INITIAL_WINDOW_DAYS', '365'))
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))


def _iso_to_dt(s: str):
    """Конвертирует ISO timestamp в datetime."""
    s2 = s.rstrip('Z')
    return datetime.fromisoformat(s2)


async def background_sync_loop(app, interval_seconds: int = 300):
    """
    Фоновый цикл синхронизации для ВСЕХ пользователей.
    Каждые interval_seconds опрашивает Ozon API для каждого активного пользователя с credentials.
    """
    logger.info(f"Фоновая синхронизация запущена (интервал={interval_seconds}с)")
    try:
        while True:
            try:
                db = SessionLocal()
                try:
                    # Получаем всех активных пользователей с активными Ozon credentials
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
    1. Получает активные credentials из БД
    2. Опрашивает Ozon API за последние RECENT_WINDOW_HOURS
    3. Сохраняет заказы в БД с user_id
    4. При необходимости обогащает данные
    """
    try:
        # Получаем активные credentials пользователя
        active_cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user.id,
            OzonCredential.is_active == True
        ).first()
        
        if not active_cred:
            logger.warning(f"У пользователя {user.email} нет активных credentials")
            return
        
        # Расшифровываем credentials
        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)
        
        if not client_id or not api_key:
            logger.error(f"Ошибка расшифровки credentials для user_id={user.id}")
            return
        
        # Период синхронизации
        since_dt = datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)
        since_iso = since_dt.replace(microsecond=0).isoformat() + 'Z'
        to_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
        
        # Запрос к Ozon API
        filter_dict = {
            'since': since_iso,
            'to': to_iso
        }
        
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
                try:
                    saved = save_order_for_user(db, user, order_data)
                    if saved:
                        total_saved += 1
                        posting_number = order_data.get('posting_number')
                        if valid_posting_number(posting_number):
                            new_postings.add(posting_number)
                except Exception as e:
                    logger.error(f"Ошибка сохранения заказа {order_data.get('posting_number')} для user_id={user.id}: {e}")
            
            if len(items) < limit:
                break
            offset += limit
        
        logger.info(f"User {user.email}: синхронизировано {total_saved} заказов")
        
        # Опционально: обогатить новые заказы
        if ENRICH_ON_FETCH and (total_saved > 0 or new_postings):
            try:
                targets = sorted(new_postings)
                for posting_number in targets:
                    try:
                        await enrich_posting_from_ozon(posting_number, user, db)
                    except Exception as e:
                        logger.debug(f"Ошибка обогащения {posting_number}: {e}")
            except Exception as e:
                logger.error(f"Ошибка обогащения для user_id={user.id}: {e}")
    
    except Exception as e:
        logger.error(f"Ошибка sync_user_orders для user_id={user.id}: {e}")


def save_order_for_user(db: Session, user: User, order_data: dict) -> bool:
    """
    Сохраняет заказ для конкретного пользователя.
    Использует PostgreSQL UPSERT для избежания дублей.
    Возвращает True если заказ был добавлен (новый).
    """
    posting_number = order_data.get('posting_number')
    if not posting_number:
        return False
    
    try:
        # UPSERT для Order (legacy таблица)
        order_id = order_data.get('order_id')
        status = order_data.get('status')
        created_at = order_data.get('created_at')
        
        # Проверяем существование
        existing = db.query(Order).filter(
            Order.user_id == user.id,
            Order.posting_number == posting_number
        ).first()
        
        if existing:
            # Обновляем
            existing.order_id = order_id
            existing.status = status
            existing.updated_at = created_at
            existing.data = order_data
            db.commit()
            return False
        else:
            # Вставляем
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
        logger.error(f"Ошибка save_order_for_user (posting={posting_number}, user_id={user.id}): {e}")
        return False


def fetch_and_save_orders(since: str, to: str, status: str, limit: int, offset: int,
                          with_analytics: bool, with_financial: bool, with_legal: bool,
                          user_id: int, db: Session) -> dict:
    """
    Получить и сохранить заказы для пользователя из Ozon API.
    Используется в analytics endpoints.
    
    Args:
        since, to: ISO timestamps
        status: фильтр статуса
        limit, offset: пагинация
        with_analytics, with_financial, with_legal: флаги данных
        user_id: ID пользователя
        db: сессия БД
    
    Returns:
        {"orders": [...]} - список полученных заказов
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"Пользователь {user_id} не найден")
            return {"orders": []}
        
        # Получаем активные credentials пользователя
        cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user_id,
            OzonCredential.is_active == True
        ).first()
        
        if not cred:
            logger.debug(f"Нет активных credentials для user_id={user_id}")
            return {"orders": []}
        
        client_id = decrypt_credential(cred.client_id_encrypted)
        api_key = decrypt_credential(cred.api_key_encrypted)
        
        # Строим фильтр для API
        filter_dict = {}
        if since:
            filter_dict["since"] = since
        if to:
            filter_dict["to"] = to
        if status:
            filter_dict["status"] = status
        
        total_saved = 0
        all_orders = []
        current_offset = offset

        while True:
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
        logger.error(f"fetch_and_save_orders ошибка для user_id={user_id}: {e}")
        return {"orders": []}


async def run_enrichment_batch(posting_numbers: list[str], user_id: int, force_refresh: bool = False) -> int:
    """
    Обогатить несколько постингов параллельно.
    
    Args:
        posting_numbers: список posting_number для обогащения
        user_id: ID пользователя
        force_refresh: если False, пропускает уже обогащённые постинги
    """
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def _run_one(pn: str):
        async with sem:
            session = SessionLocal()
            try:
                # Проверяем: есть ли уже products для этого постинга и пользователя?
                if not force_refresh:
                    existing_products = session.query(OrderProduct).filter(
                        OrderProduct.posting_number == pn,
                        OrderProduct.user_id == user_id
                    ).count()
                    if existing_products > 0:
                        logger.debug(f"Постинг {pn} уже обогащен ({existing_products} товаров), пропускаем")
                        return
                
                user = session.query(User).filter(User.id == user_id).first()
                if user:
                    await enrich_posting_from_ozon(pn, user, session)
            finally:
                session.close()

    targets = [pn for pn in posting_numbers if valid_posting_number(pn)]
    if not targets:
        return 0

    try:
        await asyncio.gather(*(_run_one(pn) for pn in targets), return_exceptions=True)
    except Exception as e:
        logger.error(f"run_enrichment_batch ошибка для user_id={user_id}: {e}")
    return len(targets)


async def initial_backfill_for_user(user: User, db: Session) -> dict:
    """
    Первичная загрузка истории для пользователя за INITIAL_WINDOW_DAYS.
    Данные подтягиваются окнами по HISTORY_WINDOW_DAYS.
    
    ВАЖНО: Устанавливает флаг is_syncing для отслеживания статуса синхронизации.
    Периодические обновления по таймеру НЕ должны трогать этот флаг!
    """
    # Получаем или создаем запись SyncStatus
    sync_status = db.query(SyncStatus).filter(
        SyncStatus.user_id == user.id
    ).first()
    
    if not sync_status:
        sync_status = SyncStatus(
            user_id=user.id,
            is_syncing=True,
            status_message="Идет загрузка данных с маркетплейса",
            sync_started_at=datetime.utcnow(),
            total_records_synced=0
        )
        db.add(sync_status)
    else:
        sync_status.is_syncing = True
        sync_status.status_message = "Идет загрузка данных с маркетплейса"
        sync_status.sync_started_at = datetime.utcnow()
        sync_status.total_records_synced = 0
    
    db.commit()
    
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=INITIAL_WINDOW_DAYS)
    window_start = start_dt
    total_saved = 0
    total_fetched = 0

    try:
        while window_start < end_dt:
            window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), end_dt)
            since_iso = window_start.replace(microsecond=0).isoformat() + 'Z'
            to_iso = window_end.replace(microsecond=0).isoformat() + 'Z'

            result = await asyncio.to_thread(
                fetch_and_save_orders,
                since_iso,
                to_iso,
                "",
                50,
                0,
                True,
                True,
                False,
                user.id,
                db
            )

            orders = result.get("orders") or []
            total_saved += result.get("saved") or 0
            total_fetched += result.get("fetched") or 0

            if ENRICH_ON_FETCH and orders:
                posting_numbers = [o.get("posting_number") for o in orders if valid_posting_number(o.get("posting_number"))]
                if posting_numbers:
                    await run_enrichment_batch(posting_numbers, user.id)

            window_start = window_end + timedelta(seconds=1)
        
        # Синхронизация успешно завершена - обновляем статус
        sync_status.is_syncing = False
        sync_status.status_message = "Данные загружены"
        sync_status.sync_completed_at = datetime.utcnow()
        sync_status.total_records_synced = total_saved
        db.commit()
        
    except Exception as e:
        # При ошибке обновляем статус и пробрасываем исключение
        sync_status.is_syncing = False
        sync_status.status_message = f"Ошибка при загрузке: {str(e)[:100]}"
        sync_status.sync_completed_at = datetime.utcnow()
        db.commit()
        raise

    return {"saved": total_saved, "fetched": total_fetched}
