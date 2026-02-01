import os
import logging
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from starlette.middleware.cors import CORSMiddleware
from db.database import get_db, Order

load_dotenv()

# Настройка логирования
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
try:
    _lvl = getattr(logging, LOG_LEVEL, logging.INFO)
except Exception:
    _lvl = logging.INFO

logger = logging.getLogger("uvicorn.error")
logger.setLevel(_lvl)

# Инициализация FastAPI
app = FastAPI(
    title="OzonAPIHub",
    description="Сервис синхронизации и аналитики заказов Ozon FBO",
    version="1.0.0"
)

# CORS для Flutter Web (dev): разрешаем запросы с localhost
# Для development разрешаем все localhost адреса и порты
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:54321",      # Flutter Web dev server
        "http://127.0.0.1:54321",      # Flutter Web dev server (127.0.0.1)
        "http://localhost:8080",       # Backend
        "http://127.0.0.1:8080",       # Backend  
        "http://localhost",            # Nginx frontend
        "http://127.0.0.1",            # Nginx frontend
    ],
    allow_origin_regex=r"http://localhost:\d+",  # Разрешаем любой порт localhost для dev
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    max_age=600  # Cache preflight for 10 minutes
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

# Инициализация фоновых задач при запуске
from services.sync import background_sync_loop

SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '300'))


@app.on_event("startup")
async def startup_event():
    """При запуске: инициализировать диагностические поля и запустить фоновую синхронизацию."""
    app.state.last_sync_new = None
    app.state.last_sync_recent = None
    app.state.last_sync_error = None
    app.state.sync_task = asyncio.create_task(background_sync_loop(app, SYNC_INTERVAL_SECONDS))


@app.on_event("shutdown")
async def shutdown_event():
    """При завершении: отменить фоновую задачу."""
    task = getattr(app.state, 'sync_task', None)
    if task:
        task.cancel()


@app.get("/stats")
async def stats(db = Depends(get_db)):
    """
    Диагностика: количество строк, min/max created_at, последние времена синхронизаций.
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
