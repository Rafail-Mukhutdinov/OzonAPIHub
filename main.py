"""
Главный модуль приложения OzonAPIHub.
Здесь инициализируется FastAPI, подключаются маршруты (роутеры),
настраивается middleware и запускаются фоновые задачи.
"""

import os
import logging
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env в самом начале работы
load_dotenv()

from fastapi import FastAPI, Depends
from starlette.middleware.cors import CORSMiddleware
from db.database import get_db, Order
from utils.rate_limit_middleware import setup_rate_limiting
from services.sync import background_sync_loop

# Инициализация кастомного логирования (см. utils/logging_config.py)
import utils.logging_config
logger = logging.getLogger("OzonAPIHub")

# Интервал между циклами фоновой синхронизации (в секундах)
SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '300'))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Контекст-менеджер жизненного цикла приложения.
    Выполняет действия при запуске и завершении сервера.
    """
    # Состояние для отслеживания статистики последней синхронизации в памяти
    app.state.last_sync_new = None
    app.state.last_sync_recent = None
    app.state.last_sync_error = None

    # Очистка "зависших" статусов синхронизации в БД.
    # Это нужно, если сервер упал или был перезагружен во время активного процесса backfill.
    try:
        from db.database import SessionLocal, SyncStatus
        db = SessionLocal()
        try:
            stuck_syncs = db.query(SyncStatus).filter(SyncStatus.is_syncing == True).all()
            for sync in stuck_syncs:
                sync.is_syncing = False
                sync.status_message = "error: interrupted by server restart"
            if stuck_syncs:
                db.commit()
                logger.info(f"Сброшено {len(stuck_syncs)} зависших статусов синхронизации.")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Ошибка при сбросе зависших статусов: {e}")

    # Запуск фонового бесконечного цикла синхронизации для всех активных пользователей
    sync_task = asyncio.create_task(background_sync_loop(app, SYNC_INTERVAL_SECONDS))
    app.state.sync_task = sync_task

    logger.info("Application OzonAPIHub started")

    yield  # Здесь приложение начинает обрабатывать HTTP-запросы

    # Действия при остановке сервера
    if sync_task:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            logger.info("Background sync task cancelled")

# Инициализация FastAPI приложения
app = FastAPI(
    title="OzonAPIHub",
    description="Сервис синхронизации и аналитики заказов Ozon FBO",
    version="1.0.0",
    lifespan=lifespan
)

# Подключаем защиту от DDoS и спама (Rate Limiting) через slowapi
setup_rate_limiting(app)

# Настройка CORS для взаимодействия с фронтендом (Flutter Web / Android)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:54321",    # Дефолтный порт Flutter Web
        "http://127.0.0.1:54321",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost",
        "http://127.0.0.1",
        "http://45.150.11.25",       # IP продакшен-сервера
        "http://45.150.11.25:8080",
    ],
    allow_origin_regex=r"http://localhost:\d+", # Разрешаем любые порты на localhost для разработки
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    max_age=600 # Кеширование preflight-запросов на 10 минут
)

@app.get("/ping")
async def ping():
    """Простой эндпоинт для проверки доступности сервера (Health Check)."""
    return {"message": "pong"}

# Импорты роутеров (маршрутов API)
from routes.analytics import router as analytics_router
from routes.orders import router as orders_router
from routes.sync_endpoints import router as sync_router
from routes.costs import router as costs_router
from routes.enrichment_endpoints import router as enrichment_router
from routes.auth_endpoints import router as auth_router

from routes.auth_endpoints import get_current_user
from fastapi import BackgroundTasks
from db.database import SyncStatus
from services.sync import initial_backfill_for_user
from datetime import datetime, timezone

# ПЕРЕХВАТ МАРШРУТОВ:
# Мы переопределяем запуск первичной синхронизации здесь,
# чтобы иметь прямой доступ к фоновым задачам (BackgroundTasks) FastAPI.
@app.post("/sync/initial/force")
@app.post("/sync/initial")
async def override_sync_initial(
    background_tasks: BackgroundTasks,
    user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Принудительный запуск полной загрузки истории заказов."""
    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == user.id).first()
    if not sync_status:
        sync_status = SyncStatus(user_id=user.id)
        db.add(sync_status)
    
    sync_status.is_syncing = True
    sync_status.status_message = "Инициализация фоновой задачи..."
    sync_status.sync_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    logger.info(f"Нажата кнопка загрузки для пользователя {user.id}. Старт...")
    # Задача уходит в фон, эндпоинт отвечает мгновенно
    background_tasks.add_task(initial_backfill_for_user, user.id, None)
    return {"status": "ok", "message": "Загрузка запущена"}

# Подключение всех модулей API к основному приложению
app.include_router(analytics_router)
app.include_router(orders_router)
app.include_router(sync_router)
app.include_router(costs_router)
app.include_router(enrichment_router)
app.include_router(auth_router)

@app.get("/stats")
def stats(db = Depends(get_db)):
    """Общая статистика сервера (количество записей, время последней синхронизации)."""
    total = db.query(Order).count()
    min_created = db.query(Order.created_at).order_by(Order.created_at.asc()).first()
    max_created = db.query(Order.created_at).order_by(Order.created_at.desc()).first()
    return {
        "total_rows": total,
        "min_created_at": min_created[0] if min_created else None,
        "max_created_at": max_created[0] if max_created else None,
        "last_sync_new": getattr(app.state, 'last_sync_new', None),
        "last_sync_error": getattr(app.state, 'last_sync_error', None),
    }
