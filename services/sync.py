import os
import logging
logger = logging.getLogger("uvicorn.error")
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from db.database import User, Order, OrderPosting, OrderProduct, SessionLocal
from services.enrichment import enrich_posting_from_ozon
from services.ozon import ozon_fbo_list_async
from utils.encryption import decrypt_credential
from utils.common import valid_posting_number

# Настройки из .env
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')


def _iso_to_dt(s: str):
    """Конвертирует ISO timestamp в datetime."""
    s2 = s.rstrip('Z')
    return datetime.fromisoformat(s2)


async def background_sync_loop(app, interval_seconds: int = 300):
    """
    Фоновый цикл синхронизации для ВСЕХ пользователей.
    Каждые interval_seconds опрашивает Ozon API для каждого активного пользователя.
    """
    logger.info(f"Фоновая синхронизация запущена (интервал={interval_seconds}с)")
    try:
        while True:
            try:
                db = SessionLocal()
                try:
                    # Получаем всех активных пользователей с настроенными Ozon credentials
                    users = db.query(User).filter(
                        User.is_active == True,
                        User.ozon_client_id.isnot(None),
                        User.ozon_api_key.isnot(None)
                    ).all()
                    
                    if not users:
                        logger.debug("Нет активных пользователей с Ozon credentials")
                    else:
                        logger.info(f"Синхронизация для {len(users)} пользователей")
                        for user in users:
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
    1. Расшифровывает credentials
    2. Опрашивает Ozon API за последние RECENT_WINDOW_HOURS
    3. Сохраняет заказы в БД с user_id
    4. При необходимости обогащает данные
    """
    try:
        # Расшифровываем credentials
        client_id = decrypt_credential(user.ozon_client_id)
        api_key = decrypt_credential(user.ozon_api_key)
        
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
        offset = 0
        limit = 50
        
        while True:
            data = await ozon_fbo_list_async(
                client_id=client_id,
                api_key=api_key,
                filter_params=filter_dict,
                limit=limit,
                offset=offset,
                with_params={"analytics_data": True, "financial_data": True}
            )
            
            items = data.get('result', []) or []
            if not items:
                break
            
            for order_data in items:
                try:
                    saved = save_order_for_user(db, user, order_data)
                    if saved:
                        total_saved += 1
                except Exception as e:
                    logger.error(f"Ошибка сохранения заказа {order_data.get('posting_number')} для user_id={user.id}: {e}")
            
            if len(items) < limit:
                break
            offset += limit
        
        logger.info(f"User {user.email}: синхронизировано {total_saved} заказов")
        
        # Опционально: обогатить новые заказы
        if ENRICH_ON_FETCH and total_saved > 0:
            try:
                # Получаем постинги, которые еще не обогащены
                postings = db.query(OrderPosting.posting_number).filter(
                    OrderPosting.user_id == user.id,
                    OrderPosting.created_at >= since_iso
                ).all()
                
                for (posting_number,) in postings:
                    if valid_posting_number(posting_number):
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
