"""
Главный модуль приложения OzonAPIHub.

Назначение приложения:
OzonAPIHub — это бэкенд-сервис для автоматизации работы с маркетплейсом Ozon (FBO/FBS).
Основные функции включают:
- Синхронизацию заказов и отправлений через Ozon API.
- Аналитику продаж, расчет прибыли и учет себестоимости товаров.
- Управление обогащением данных (дополнительная информация о товарах).
- Поддержку мобильного приложения (OTA-обновления).
- Ролевую модель доступа (пользователи и администраторы).

В этом файле инициализируется FastAPI, подключаются маршруты (роутеры),
настраивается middleware (CORS, Rate Limiting) и запускаются фоновые задачи через воркеры.
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
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from db.database import get_db, Order, User, engine, Base, SessionLocal, SyncStatus, init_db
from utils.rate_limit_middleware import setup_rate_limiting
from utils.auth import get_current_user
from services.ozon import init_http_client, close_http_client

# Инициализация кастомного логирования (см. utils/logging_config.py)
import utils.logging_config
logger = logging.getLogger("OzonAPIHub")

# URL для подключения к Redis, используется для очереди задач ARQ
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

    # 3. Инициализация пула задач ARQ (Redis) для постановки задач воркерам
    try:
        app.state.arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
        logger.info("ARQ Task Pool initialized")
    except Exception as e:
        logger.error(f"Failed to initialize ARQ pool: {e}")

    # 4. Очистка "зависших" статусов синхронизации в БД.
    # Если сервер упал во время синхронизации, флаг is_syncing останется True.
    # Сбрасываем его при старте, чтобы воркеры могли начать новую синхронизацию.
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

# Инициализация основного объекта FastAPI приложения
app = FastAPI(
    title="OzonAPIHub",
    description="Сервис синхронизации и аналитики заказов Ozon FBO с параллельной обработкой",
    version="1.1.0",
    lifespan=lifespan,
    strict_slashes=False
)

# Подключаем защиту от DDoS и спама (ограничение частоты запросов)
setup_rate_limiting(app)

# Настройка CORS (Cross-Origin Resource Sharing)
# Определяет, каким фронтенд-доменам разрешено обращаться к этому API.
cors_origins_str = os.getenv("CORS_ORIGINS", "https://seller.home-me.online")
if cors_origins_str == "*":
    # Явный wildcard: разрешаем всем, но credentials при этом запрещены.
    # Для локальной веб-разработки задайте CORS_ORIGINS=* в .env
    origins = [] 
    allow_all_origins = True
else:
    origins = [o.strip() for o in cors_origins_str.split(",") if o.strip()]
    allow_all_origins = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_origins else origins,
    allow_credentials=not allow_all_origins, # credentials запрещены при allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600 # Время кэширования предварительного запроса (preflight request) в секундах
)

@app.get("/ping")
async def ping():
    """Эндпоинт для проверки работоспособности сервиса."""
    return {"message": "pong"}

# Структура API эндпоинтов:
# Приложение разделено на функциональные модули через APIRouter.
# Каждый роутер отвечает за свою область ответственности.

from routes.analytics import router as analytics_router
from routes.orders import router as orders_router
from routes.sync_endpoints import router as sync_router
from routes.costs import router as costs_router
from routes.product_costs import router as product_costs_router
from routes.enrichment_endpoints import router as enrichment_router
from routes.auth_endpoints import router as auth_router
from routes.app_updates import router as app_updates_router
from routes.admin import router as admin_router

# Регистрация роутеров в приложении:
app.include_router(analytics_router)          # Аналитика и дашборды
app.include_router(orders_router)             # Список и детализация заказов
app.include_router(sync_router)               # Управление ручной и авто-синхронизацией
app.include_router(costs_router)              # Общие затраты и финансовые настройки
app.include_router(product_costs_router)      # Учет себестоимости конкретных товаров
app.include_router(enrichment_router)         # Обогащение данных товаров
app.include_router(auth_router)               # Аутентификация и управление профилем
app.include_router(app_updates_router)        # Проверка и скачивание обновлений приложения
app.include_router(admin_router)              # Админ-панель и управление пользователями

# -----------------------------------------------------------------------------
# Статические файлы (APK для OTA-обновлений мобильного приложения и пр.)
# Прямая ссылка на скачивание APK: /static/apps/app-release.apk
# (каталог static монтируется в контейнер через volume: ./static:/app/static)
# -----------------------------------------------------------------------------
os.makedirs(os.path.join("static", "apps"), exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
