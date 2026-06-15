"""
Модуль воркера ARQ для асинхронной обработки задач.
Здесь определяются задачи, которые будут выполняться в фоне.
"""

import asyncio
import logging
from arq import cron
from db.database import SessionLocal, User, SyncStatus
from services.sync import sync_user_orders, initial_backfill_for_user
from utils.logging_config import setup_logging
import os

# Настройка логирования для воркера
setup_logging()
logger = logging.getLogger("OzonAPIHub.worker")

async def sync_all_users_task(ctx):
    """Задача по расписанию: синхронизация недавних заказов всех активных пользователей."""
    logger.info("Запуск плановой синхронизации всех пользователей (Трек Б)")
    db = SessionLocal()
    try:
        from db.database import OzonCredential
        users = db.query(User).join(User.ozon_credentials).filter(
            User.is_active == True,
            OzonCredential.is_active == True
        ).distinct().all()

        if not users:
            logger.info("Нет активных пользователей для синхронизации")
            return

        for user in users:
            # В будущем здесь можно будет запускать подзадачи для каждого пользователя
            # Но для начала выполним последовательно внутри воркера
            await sync_user_orders(user, db)
    except Exception as e:
        logger.error(f"Ошибка в задаче sync_all_users_task: {e}")
    finally:
        db.close()

async def initial_backfill_task(ctx, user_id: int):
    """Задача: Полная загрузка истории для конкретного пользователя (Трек А)."""
    logger.info(f"Запуск исторической загрузки для пользователя {user_id}")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            await initial_backfill_for_user(user, db)
        else:
            logger.error(f"Пользователь {user_id} не найден для backfill")
    except Exception as e:
        logger.error(f"Ошибка в задаче initial_backfill_task для {user_id}: {e}")
    finally:
        db.close()

async def startup(ctx):
    """Действия при запуске воркера."""
    logger.info("Воркер запущен и готов к работе")

async def shutdown(ctx):
    """Действия при остановке воркера."""
    logger.info("Воркер останавливается...")

class WorkerSettings:
    """Настройки воркера arq."""
    redis_settings = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    on_startup = startup
    on_shutdown = shutdown
    functions = [sync_all_users_task, initial_backfill_task]

    # Расписание для Трека Б (недавние заказы) - каждые 5 минут
    # Можно будет сделать адаптивным в будущем
    cron_jobs = [
        cron(sync_all_users_task, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55})
    ]
