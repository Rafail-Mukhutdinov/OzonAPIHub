import os
import logging
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from starlette.middleware.cors import CORSMiddleware
from db.database import get_db, Order
from services.sync import background_sync_loop

# Инициализация нашего кастомного логирования
import utils.logging_config
logger = logging.getLogger("OzonAPIHub")

load_dotenv()

SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '300'))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Контекст-менеджер жизненного цикла приложения."""
    app.state.last_sync_new = None
    app.state.last_sync_recent = None
    app.state.last_sync_error = None

    # Сброс зависших статусов синхронизации (если сервер был перезагружен во время backfill)
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

    # Запуск фоновой синхронизации
    sync_task = asyncio.create_task(background_sync_loop(app, SYNC_INTERVAL_SECONDS))
    app.state.sync_task = sync_task

    logger.info("Application OzonAPIHub started")

    yield

    if sync_task:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            logger.info("Background sync task cancelled")

app = FastAPI(
    title="OzonAPIHub",
    description="Сервис синхронизации и аналитики заказов Ozon FBO",
    version="1.0.0",
    lifespan=lifespan
)

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

@app.get("/ping")
async def ping():
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
