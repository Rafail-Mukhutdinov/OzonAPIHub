"""
Модуль воркера ARQ для асинхронной обработки фоновых задач.

Жизненный цикл фоновых задач:
1. Задачи ставятся в очередь Redis основным приложением (FastAPI) или планировщиком (cron).
2. Воркер (отдельный процесс) извлекает задачи из очереди.
3. Воркер инициализирует собственное соединение с БД и HTTP-клиент.
4. Выполняется логика задачи (например, синхронизация с Ozon API).
5. Результаты сохраняются в БД, флаги блокировок (is_syncing) снимаются.

Воркер реализует адаптивные интервалы опроса (Adaptive Polling), что позволяет
экономить лимиты Ozon API, опрашивая активные магазины чаще, а неактивные — реже.
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

async def sync_all_users_task(ctx):
    """
    Задача по расписанию: синхронизация всех активных пользователей.
    
    Логика Adaptive Polling:
    - Частота опроса зависит от времени последней продажи (по данным МСК).
    - Если последняя продажа была < 1 часа назад: интервал 1 минута.
    - Если продажа была сегодня: интервал 5 минут.
    - В остальных случаях: интервал 15 минут.
    
    Это обеспечивает актуальность данных для активных продавцов при минимальной нагрузке.
    """
    now = get_now_utc()
    db = SessionLocal()
    try:
        from db.database import OzonCredential
        # Выбираем всех активных пользователей с активными ключами API Ozon
        users = db.query(User).join(User.ozon_credentials).filter(
            User.is_active == True,
            OzonCredential.is_active == True
        ).distinct().all()

        if not users:
            logger.debug("sync_all_users_task: нет пользователей с активными credentials")
            return

        logger.debug(f"sync_all_users_task: найдено {len(users)} пользователей для проверки")

        for user in users:
            # Получаем или создаем статус синхронизации для пользователя
            status = db.query(SyncStatus).filter(SyncStatus.user_id == user.id).first()
            if not status:
                status = SyncStatus(user_id=user.id)
                db.add(status)
                db.commit()
                db.refresh(status)

            # --- ЛОГИКА АДАПТИВНОГО ОПРОСА (ADAPTIVE POLLING) ---
            # Проверяем обе схемы (FBO и FBS), чтобы понять общую активность магазина
            last_fbo = get_latest_order_datetime(db, user.id, scheme='fbo')
            last_fbs = get_latest_order_datetime(db, user.id, scheme='fbs')
            
            last_dt = None
            if last_fbo and last_fbs:
                last_dt = max(last_fbo, last_fbs)
            else:
                last_dt = last_fbo or last_fbs

            interval_minutes = 15 # Значение по умолчанию

            if last_dt:
                try:
                    # Сравниваем текущее время и время заказа в MSК
                    now_msk = to_msk(get_now_utc())
                    last_order_msk = to_msk(last_dt)
                    diff = get_now_utc() - last_dt

                    if diff < timedelta(hours=1):
                        interval_minutes = 1 # Очень активно: раз в минуту
                    elif last_order_msk.date() == now_msk.date():
                        interval_minutes = 5 # Активно (сегодня были продажи): раз в 5 минут
                except Exception as e:
                    logger.warning(f"Error calculating adaptive interval for user {user.id}: {e}")
                    interval_minutes = 5

            # Проверяем, пришло ли время для новой синхронизации
            last_sync = status.last_sync_attempt_at if status.last_sync_attempt_at else (get_now_utc() - timedelta(days=1))
            elapsed = get_now_utc() - last_sync
            if elapsed < timedelta(minutes=interval_minutes):
                logger.debug(
                    f"User {user.id}: пропущен (с последней синхронизации прошло "
                    f"{int(elapsed.total_seconds())}с, интервал {interval_minutes}м)"
                )
                continue

            # 1. АТОМАРНАЯ УСТАНОВКА БЛОКИРОВКИ
            # Предотвращает одновременный запуск нескольких задач синхронизации для одного пользователя.
            updated = db.query(SyncStatus).filter(
                SyncStatus.user_id == user.id, 
                SyncStatus.is_syncing == False
            ).update({
                SyncStatus.is_syncing: True, 
                SyncStatus.sync_started_at: get_now_utc(),
                SyncStatus.last_sync_attempt_at: get_now_utc()
            }, synchronize_session=False)
            db.commit()

            if not updated:
                logger.warning(f"User {user.id}: Синхронизация уже занята другим воркером. Пропуск.")
                continue

            logger.info(f"User {user.id}: Запуск адаптивной синхронизации (интервал {interval_minutes}м)")

            # 3. ВЫПОЛНЕНИЕ СИНХРОНИЗАЦИИ
            try:
                activity_found = await sync_user_orders(user, db)
            except Exception as e:
                logger.error(f"User {user.id}: Критическая ошибка при синхронизации: {e}", exc_info=True)
            finally:
                # 4. СНЯТИЕ БЛОКИРОВКИ
                # Гарантированно снимаем флаг is_syncing, даже если возникла ошибка.
                try:
                    db.rollback() 
                    db.refresh(status)
                    status.is_syncing = False
                    status.sync_completed_at = get_now_utc()
                    db.commit()
                except Exception as ef:
                    logger.error(f"User {user.id}: Failed to release lock: {ef}")

    except Exception as e:
        logger.error(f"Ошибка в адаптивном планировщике: {e}", exc_info=True)
    finally:
        db.close()

async def initial_backfill_task(ctx, user_id: int):
    """
    Задача: Полная загрузка истории заказов для нового пользователя (Backfill).
    Загружает данные за длительный период (обычно 1-2 года), чтобы построить аналитику.
    """
    job_id = f"backfill_user_{user_id}"
    
    logger.info(f"--- [WORKER] Начало задачи {job_id} ---")
    db = SessionLocal()
    try:
        st = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        
        # Защита от "зомби"-задач: если флаг стоит, но активности нет > 10 минут, считаем задачу зависшей.
        now = get_now_utc()
        if st and st.is_syncing:
            last_activity = st.updated_at or st.sync_started_at
            if last_activity and (now - last_activity).total_seconds() < 600:
                logger.warning(f"Backfill for user {user_id} is already in progress. Skipping.")
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
    """
    Задача: Принудительная загрузка данных за конкретный период.
    Используется для ручного пересчета или восстановления данных.
    """
    db = SessionLocal()
    try:
        from services.sync import sync_range_for_user
        # Парсим даты из ISO формата
        start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
        
        await sync_range_for_user(user_id, start_dt, end_dt, db)
    except Exception as e:
        logger.error(f"Ошибка в history_sync_task для юзера {user_id}: {e}", exc_info=True)
        # На всякий случай сбрасываем статус, если sync_range_for_user упал раньше, чем успел сам обработать
        st = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if st and st.is_syncing:
            st.is_syncing = False
            st.status_message = f"Error: Task: {str(e)[:100]}"
            db.commit()
    finally:
        db.close()

async def startup(ctx):
    """Действия при запуске процесса воркера."""
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
    """Действия при корректном завершении процесса воркера."""
    logger.info("Воркер останавливается...")
    await close_http_client()
    logger.info("HTTP client for Ozon API closed by worker")

class WorkerSettings:
    """Настройки воркера ARQ."""
    # Параметры подключения к Redis
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    
    # Коллбэки жизненного цикла
    on_startup = startup
    on_shutdown = shutdown
    
    # Список доступных функций, которые может выполнять этот воркер
    functions = [sync_all_users_task, initial_backfill_task, history_sync_task]
    
    # Максимальное время выполнения одной задачи (1 час)
    job_timeout = 3600 

    # Крон запускается КАЖДУЮ МИНУТУ.
    # Внутри sync_all_users_task реализована проверка интервалов (Adaptive Polling),
    # чтобы не делать лишних запросов к API, если время еще не пришло.
    cron_jobs = [
        cron(sync_all_users_task, second=0)
    ]
