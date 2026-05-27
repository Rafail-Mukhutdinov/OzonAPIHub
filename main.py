import os
import logging
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from starlette.middleware.cors import CORSMiddleware
from db.database import get_db, Order
from services.sync import background_sync_loop

load_dotenv()

# Настройка логирования
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("uvicorn.error")

SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '300'))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Контекст-менеджер жизненного цикла приложения (заменяет startup/shutdown)."""
    # Инициализация диагностических полей
    app.state.last_sync_new = None
    app.state.last_sync_recent = None
    app.state.last_sync_error = None

    # Запуск фоновой синхронизации
    sync_task = asyncio.create_task(background_sync_loop(app, SYNC_INTERVAL_SECONDS))
    app.state.sync_task = sync_task

    logger.info("Application started, background sync task created")

    yield

    # Завершение
    if sync_task:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            logger.info("Background sync task cancelled")

# Инициализация FastAPI
app = FastAPI(
    title="OzonAPIHub",
    description="Сервис синхронизации и аналитики заказов Ozon FBO",
    version="1.0.0",
    lifespan=lifespan
)

# CORS конфигурация
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:54321",
        "http://127.0.0.1:54321",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost",
        "http://127.0.0.1",
        "http://45.150.11.25",
        "http://45.150.11.25:8080",
    ],
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    max_age=600
)

# Здоровье-чек
@app.get("/ping")
async def ping():
    logger.info('запрос на ping')
    return {"message": "pong"}

# Подключение роутеров
from routes.analytics import router as analytics_router
from routes.orders import router as orders_router
from routes.sync_endpoints import router as sync_router
from routes.costs import router as costs_router
from routes.enrichment_endpoints import router as enrichment_router
from routes.auth_endpoints import router as auth_router

app.include_router(analytics_router)
app.include_router(orders_router)
app.include_router(sync_router)
app.include_router(costs_router)
app.include_router(enrichment_router)
app.include_router(auth_router)

@app.get("/stats")
def stats(db = Depends(get_db)):
    """
    Диагностика: количество строк, min/max created_at, последние времена синхронизаций.
    Используем синхронный эндпоинт для синхронных запросов к БД.
    """
    total = db.query(Order).count()
    min_created = db.query(Order.created_at).order_by(Order.created_at.asc()).first()
    max_created = db.query(Order.created_at).order_by(Order.created_at.desc()).first()
    return {
        "total_rows": total,
        "min_created_at": min_created[0] if min_created else None,
        "max_created_at": max_created[0] if max_created else None,
        "last_sync_new": getattr(app.state, 'last_sync_new', None),
        "last_sync_new_saved": getattr(app.state, 'last_sync_new_saved', None),
        "last_sync_new_fetched": getattr(app.state, 'last_sync_new_fetched', None),
        "last_sync_recent": getattr(app.state, 'last_sync_recent', None),
        "last_sync_recent_saved": getattr(app.state, 'last_sync_recent_saved', None),
        "last_sync_recent_fetched": getattr(app.state, 'last_sync_recent_fetched', None),
        "last_sync_error": getattr(app.state, 'last_sync_error', None),
        "sync_interval_seconds": getattr(app.state, 'last_sync_interval_seconds', SYNC_INTERVAL_SECONDS),
    }
