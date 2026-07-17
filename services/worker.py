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
from services.sync import sync_user_orders, initial_backfill_for_user, get_latest_order_datetime, sync_range_for_user
from services.ozon import init_http_client, close_http_client
from utils.common import to_msk, parse_ozon_datetime, get_now_utc
import utils.logging_config
import os

logger = logging.getLogger("OzonAPIHub.worker")

def _get_now_utc():
    return get_now_utc()

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
            if not status:
                status = SyncStatus(user_id=user.id)
                db.add(status)
                db.commit()
                db.refresh(status)

            # --- ADAPTIVE POLLING LOGIC ---
            last_dt = get_latest_order_datetime(db, user.id)
            interval_minutes = 15

            if last_dt:
                try:
                    # Сравниваем в MSК
                    now_msk = to_msk(_get_now_utc())
                    last_order_msk = to_msk(last_dt)
                    diff = _get_now_utc() - last_dt

                    if diff < timedelta(hours=1):
                        interval_minutes = 1
                    elif last_order_msk.date() == now_msk.date():
                        interval_minutes = 5
                except Exception as e:
                    logger.warning(f"Error calculating adaptive interval for user {user.id}: {e}")
                    interval_minutes = 5

            last_sync = status.last_sync_attempt_at if status.last_sync_attempt_at else (_get_now_utc() - timedelta(days=1))
            elapsed = _get_now_utc() - last_sync
            if elapsed < timedelta(minutes=interval_minutes):
                logger.debug(
                    f"User {user.id}: пропущен (с последней синхронизации прошло "
                    f"{int(elapsed.total_seconds())}с, интервал {interval_minutes}м)"
                )
                continue

            # 1. АТОМАРНАЯ УСТАНОВКА БЛОКИРОВКИ (Риск A)
            updated = db.query(SyncStatus).filter(
                SyncStatus.user_id == user.id, 
                SyncStatus.is_syncing == False
            ).update({
                SyncStatus.is_syncing: True, 
                SyncStatus.sync_started_at: _get_now_utc(),
                SyncStatus.last_sync_attempt_at: _get_now_utc()
            }, synchronize_session=False)
            db.commit()

            if not updated:
                logger.warning(f"User {user.id}: Синхронизация уже занята другим воркером. Пропуск.")
                continue

            logger.info(f"User {user.id}: Запуск адаптивной синхронизации (интервал {interval_minutes}м)")

            # 3. БЕЗОПАСНОЕ ВЫПОЛНЕНИЕ
            try:
                activity_found = await sync_user_orders(user, db)
            except Exception as e:
                logger.error(f"User {user.id}: Критическая ошибка при синхронизации: {e}", exc_info=True)
            finally:
                # 4. СНЯТИЕ БЛОКИРОВКИ (Риск B: Гарантия сброса транзакции и снятия флага)
                try:
                    db.rollback() 
                    db.refresh(status)
                    status.is_syncing = False
                    status.sync_completed_at = _get_now_utc()
                    db.commit()
                except Exception as ef:
                    logger.error(f"User {user.id}: Failed to release lock: {ef}")

    except Exception as e:
        logger.error(f"Ошибка в адаптивном планировщике: {e}", exc_info=True)
    finally:
        db.close()

async def initial_backfill_task(ctx, user_id: int):
    """Задача: Полная загрузка истории для конкретного пользователя."""
    # Защита от двойного запуска
    job_id = f"backfill_user_{user_id}"
    
    logger.info(f"--- [WORKER] Начало задачи {job_id} ---")
    db = SessionLocal()
    try:
        # Проверяем статус в БД, чтобы не запускать если уже идет (дополнительная защита)
        from db.database import SyncStatus
        st = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        
        # Если задача запущена менее 10 минут назад и флаг is_syncing стоит, 
        # возможно она еще работает. Если прошло больше — считаем зависшей.
        now = get_now_utc()
        if st and st.is_syncing:
            last_activity = st.updated_at or st.sync_started_at
            if last_activity and (now - last_activity).total_seconds() < 600:
                logger.warning(f"Backfill for user {user_id} is already in progress (last activity {int((now - last_activity).total_seconds())}s ago). Skipping.")
                return
            else:
                logger.info(f"User {user_id}: Found zombie sync flag (older than 10m). Overriding.")

        user = db.query(User).filter(User.id == user_id).first()
        if user:
            await initial_backfill_for_user(user, db)
        else:
            logger.error(f"Пользователь {user_id} не найден в БД!")
    except Exception as e:
        logger.error(f"Ошибка в initial_backfill_task: {e}", exc_info=True)
    finally:
        db.close()

async def history_sync_task(ctx, user_id: int, start_iso: str, end_iso: str):
    """Задача: Загрузка данных за конкретный период."""
    db = SessionLocal()
    try:
        from services.sync import sync_range_for_user
        start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
        
        await sync_range_for_user(user_id, start_dt, end_dt, db)
    except Exception as e:
        logger.error(f"Ошибка в history_sync_task: {e}", exc_info=True)
    finally:
        db.close()

async def startup(ctx):
    from db.database import init_db, SyncStatus, SessionLocal
    init_db()
    
    # Сбрасываем зависшие флаги синхронизации при старте воркера
    db = SessionLocal()
    try:
        db.query(SyncStatus).update({SyncStatus.is_syncing: False, SyncStatus.status_message: "Restarted"})
        db.commit()
        logger.info("Zombie sync tasks cleared on startup")
    except Exception as e:
        logger.error(f"Error clearing sync status: {e}")
    finally:
        db.close()

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
    functions = [sync_all_users_task, initial_backfill_task, history_sync_task]
    job_timeout = 3600 # Увеличили до 1 часа для тяжелых задач типа Backfill

    # Крон запускается КАЖДУЮ МИНУТУ, но логика внутри решит,
    # нужно ли делать реальный запрос к Ozon для конкретного пользователя.
    cron_jobs = [
        cron(sync_all_users_task, second=0)
    ]
