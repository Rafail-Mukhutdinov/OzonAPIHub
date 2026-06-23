"""
Главный модуль приложения OzonAPIHub.
Здесь инициализируется FastAPI, подключаются маршруты (роутеры),
настраивается middleware и запускаются фоновые задачи через воркеры.
"""

import os
import logging
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from arq import create_pool
from arq.connections import RedisSettings

# Загружаем переменные окружения из файла .env в самом начале работы
load_dotenv()

from fastapi import FastAPI, Depends
from starlette.middleware.cors import CORSMiddleware
from db.database import get_db, Order, engine, Base, SessionLocal, SyncStatus, init_db
from utils.rate_limit_middleware import setup_rate_limiting
from utils.auth import get_current_user
from services.ozon import init_http_client, close_http_client

# Инициализация кастомного логирования (см. utils/logging_config.py)
import utils.logging_config
logger = logging.getLogger("OzonAPIHub")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Контекст-менеджер жизненного цикла приложения.
    Выполняет действия при запуске и завершении сервера.
    """
    # 1. Инициализируем БД и выполняем миграции
    init_db()
    logger.info("Database initialized and migrations applied")

    # 2. Инициализация пула соединений httpx для запросов к Ozon API (keep-alive)
    app.state.http_client = init_http_client()

    # 3. Инициализация пула задач ARQ (Redis)
    try:
        app.state.arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
        logger.info("ARQ Task Pool initialized")
    except Exception as e:
        logger.error(f"Failed to initialize ARQ pool: {e}")

    # 3. Очистка "зависших" статусов синхронизации в БД.
    try:
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

    logger.info("Application OzonAPIHub started (API only mode)")

    yield  # Здесь приложение начинает обрабатывать HTTP-запросы

    # Действия при остановке сервера
    if hasattr(app.state, 'arq_pool'):
        await app.state.arq_pool.close()
        logger.info("ARQ Task Pool closed")

    # Закрываем пул соединений к Ozon API
    await close_http_client()

# Инициализация FastAPI приложения
app = FastAPI(
    title="OzonAPIHub",
    description="Сервис синхронизации и аналитики заказов Ozon FBO с параллельной обработкой",
    version="1.1.0",
    lifespan=lifespan,
    strict_slashes=False
)

# Подключаем защиту от DDoS и спама (Rate Limiting)
setup_rate_limiting(app)

# Настройка CORS
# Для SaaS версии на сервере разрешаем все источники (Origins),
# так как браузер может обращаться по IP или разным доменам.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600
)

@app.get("/ping")
async def ping():
    return {"message": "pong"}

# Импорты роутеров
from routes.analytics import router as analytics_router
from routes.orders import router as orders_router
from routes.sync_endpoints import router as sync_router
from routes.costs import router as costs_router
from routes.enrichment_endpoints import router as enrichment_router
from routes.auth_endpoints import router as auth_router

# Подключение всех модулей API
app.include_router(analytics_router)
app.include_router(orders_router)
app.include_router(sync_router)
app.include_router(costs_router)
app.include_router(enrichment_router)
app.include_router(auth_router)

@app.get("/stats")
def stats(db = Depends(get_db)):
    total = db.query(Order).count()
    return {
        "total_rows": total,
        "mode": "distributed_workers"
    }
