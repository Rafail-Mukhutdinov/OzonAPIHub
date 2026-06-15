"""
Модуль воркера ARQ для асинхронной обработки задач.
Реализует адаптивные интервалы опроса (Adaptive Polling).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from arq import cron
from arq.connections import RedisSettings
from db.database import SessionLocal, User, SyncStatus, Order
from sqlalchemy import desc
from services.sync import sync_user_orders, initial_backfill_for_user
import utils.logging_config
import os

logger = logging.getLogger("OzonAPIHub.worker")

def _get_now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

async def sync_all_users_task(ctx):
    """
    Задача по расписанию: синхронизация всех активных пользователей.
    Реализует Adaptive Polling: частота зависит от времени последней продажи.
    """
    now = _get_now_utc()
    db = SessionLocal()
    try:
        from db.database import OzonCredential
        users = db.query(User).join(User.ozon_credentials).filter(
            User.is_active == True,
            OzonCredential.is_active == True
        ).distinct().all()

        if not users:
            return

        for user in users:
            # --- ADAPTIVE POLLING LOGIC ---
            status = db.query(SyncStatus).filter(SyncStatus.user_id == user.id).first()

            # Определяем интервал на основе последней продажи
            last_order = db.query(Order).filter(Order.user_id == user.id).order_by(desc(Order.created_at)).first()

            interval_minutes = 15 # По умолчанию (Эко-режим)

            if last_order and last_order.created_at:
                try:
                    last_dt = datetime.fromisoformat(last_order.created_at.replace('Z', ''))
                    diff = now - last_dt

                    if diff < timedelta(hours=1):
                        interval_minutes = 1  # Турбо: продажи были менее часа назад
                    elif diff < timedelta(hours=24):
                        interval_minutes = 5  # Стандарт: продажи были сегодня
                except:
                    interval_minutes = 5

            # Проверяем, пришло ли время для синхронизации
            last_sync = status.updated_at if status and status.updated_at else (now - timedelta(days=1))
            if now - last_sync < timedelta(minutes=interval_minutes):
                # Еще не время
                continue

            logger.info(f"User {user.id}: Запуск адаптивной синхронизации (интервал {interval_minutes}м)")
            # Сама функция синхронизации теперь возвращает True, если нашли новые заказы
            activity_found = await sync_user_orders(user, db)

            # Если нашли новые заказы — принудительно обновим время в статусе,
            # чтобы следующий запуск в "Турбо" был через минуту
            if activity_found and status:
                status.updated_at = _get_now_utc()
                db.commit()

    except Exception as e:
        logger.error(f"Ошибка в адаптивном планировщике: {e}", exc_info=True)
    finally:
        db.close()

async def initial_backfill_task(ctx, user_id: int):
    """Задача: Полная загрузка истории для конкретного пользователя."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            await initial_backfill_for_user(user, db)
    finally:
        db.close()

async def startup(ctx):
    logger.info("Воркер запущен. Режим: Adaptive Polling (1/5/15 мин)")

async def shutdown(ctx):
    logger.info("Воркер останавливается...")

class WorkerSettings:
    """Настройки воркера arq."""
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    on_startup = startup
    on_shutdown = shutdown
    functions = [sync_all_users_task, initial_backfill_task]
    job_timeout = 900

    # Крон запускается КАЖДУЮ МИНУТУ, но логика внутри решит,
    # нужно ли делать реальный запрос к Ozon для конкретного пользователя.
    cron_jobs = [
        cron(sync_all_users_task, second=0)
    ]
