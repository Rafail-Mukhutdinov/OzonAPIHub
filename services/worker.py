"""
Модуль воркера ARQ для асинхронной обработки задач.
Реализует адаптивные интервалы опроса (Adaptive Polling).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from arq import cron
from arq.connections import RedisSettings
from db.database import SessionLocal, User, SyncStatus, Order, OrderPosting
from sqlalchemy import desc, func
from services.sync import sync_user_orders, initial_backfill_for_user, get_latest_order_datetime
from services.ozon import init_http_client, close_http_client
from utils.common import to_msk, parse_ozon_datetime
import utils.logging_config
import os

logger = logging.getLogger("OzonAPIHub.worker")

def _get_now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

async def sync_all_users_task(ctx):
    """
    Задача по расписанию: синхронизация всех активных пользователей.
    Реализует Adaptive Polling: частота зависит от времени последней продажи (МСК).
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
            logger.debug("sync_all_users_task: нет пользователей с активными credentials")
            return

        logger.debug(f"sync_all_users_task: найдено {len(users)} пользователей для проверки")

        for user in users:
            status = db.query(SyncStatus).filter(SyncStatus.user_id == user.id).first()

            # --- ADAPTIVE POLLING LOGIC ---
            # Надежно ищем последний заказ в обеих таблицах
            last_dt = get_latest_order_datetime(db, user.id)

            interval_minutes = 15 # Эко: активности давно нет

            if last_dt:
                try:
                    diff = now - last_dt

                    # Сравниваем в MSК
                    now_msk = to_msk(now)
                    last_order_msk = to_msk(last_dt)

                    if diff < timedelta(hours=1):
                        interval_minutes = 1  # Турбо: продажа менее часа назад
                    elif last_order_msk.date() == now_msk.date():
                        interval_minutes = 5  # Стандарт: продажи были сегодня по МСК
                except Exception as e:
                    logger.warning(f"Error calculating adaptive interval for user {user.id}: {e}")
                    interval_minutes = 5

            # Проверяем, пришло ли время для синхронизации
            last_sync = status.updated_at if status and status.updated_at else (now - timedelta(days=1))
            elapsed = now - last_sync
            if elapsed < timedelta(minutes=interval_minutes):
                logger.debug(
                    f"User {user.id}: пропущен (с последней синхронизации прошло "
                    f"{int(elapsed.total_seconds())}с, интервал {interval_minutes}м)"
                )
                continue

            logger.info(f"User {user.id}: Запуск адаптивной синхронизации (интервал {interval_minutes}м)")
            activity_found = await sync_user_orders(user, db)

            if status:
                status.updated_at = _get_now_utc()
                db.commit()

    except Exception as e:
        logger.error(f"Ошибка в адаптивном планировщике: {e}", exc_info=True)
    finally:
        db.close()

async def initial_backfill_task(ctx, user_id: int):
    """Задача: Полная загрузка истории для конкретного пользователя."""
    logger.info(f"--- [WORKER] Получена задача initial_backfill_task для пользователя {user_id} ---")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            await initial_backfill_for_user(user, db)
        else:
            logger.error(f"--- [WORKER] Пользователь {user_id} не найден в БД! ---")
    except Exception as e:
        logger.error(f"--- [WORKER] Ошибка в initial_backfill_task: {e} ---")
    finally:
        db.close()

async def startup(ctx):
    from db.database import init_db
    init_db()
    logger.info("Database initialized and migrations applied by worker")
    # Инициализируем пул соединений к Ozon API для долгоживущего цикла воркера
    init_http_client()
    logger.info("Воркер запущен. Режим: Adaptive Polling (1/5/15 мин)")

async def shutdown(ctx):
    logger.info("Воркер останавливается...")
    await close_http_client()
    logger.info("HTTP client for Ozon API closed by worker")

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
