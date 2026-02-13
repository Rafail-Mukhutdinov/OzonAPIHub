# 🗺️ План развития OzonAPIHub

**Дата создания:** 13 февраля 2026 г.  
**Статус:** В разработке  
**Версия:** 1.1.0

---

## 📋 Текущие ограничения и план их устранения

### Критичность проблем

| Приоритет | Проблема | Риск | Сложность | Время | Статус |
|-----------|----------|------|-----------|-------|--------|
| 🔴 **P0** | Rate limiting отсутствует | Высокий | Средняя | 2-3 дня | ⏳ Not Started |
| 🟡 **P1** | Нет кеширования | Средний | Средняя | 3-4 дня | ⏳ Not Started |
| 🟡 **P1** | CORS для production | Средний | Низкая | 1 день | ⏳ Not Started |
| 🟢 **P2** | Алембик миграции | Низкий | Средняя | 2 дня | ⏳ Not Started |
| 🟢 **P3** | Ozon API timeout | Низкий | Низкая | 1 день | ⏳ Not Started |

**Легенда статусов:**
- ⏳ Not Started — не начато
- 🏗️ In Progress — в разработке
- ✅ Done — завершено
- ⚠️ Blocked — заблокировано

---

## 🎯 Sprint Planning

### Sprint 1: Критичные улучшения (5 дней)

**Цель:** Защитить систему от перегрузок и ускорить отклик

#### День 1-2: Rate Limiting
- [ ] Установить Redis
- [ ] Создать `utils/rate_limiter.py`
- [ ] Создать `middleware/rate_limit_middleware.py`
- [ ] Интегрировать в `main.py`
- [ ] Добавить настройки в `.env`
- [ ] Написать тесты `scripts/test_rate_limit.py`
- [ ] Протестировать превышение лимитов

**Критерии приёмки:**
- ✓ 429 ответ при превышении лимита пользователя (10 req/min)
- ✓ Глобальный лимит не превышается (100 req/min)
- ✓ Redis работает и хранит счётчики

#### День 3-4: Кеширование (базовое)
- [ ] Создать `utils/cache_manager.py`
- [ ] Создать `utils/cache_decorator.py`
- [ ] Применить кеширование к аналитике (`routes/analytics.py`)
- [ ] Реализовать инвалидацию в `services/enrichment.py`
- [ ] Добавить метрики cache hit/miss
- [ ] Протестировать на реальных данных

**Критерии приёмки:**
- ✓ Cache hit rate > 60% для аналитики
- ✓ Время ответа аналитики < 100ms (с кешем)
- ✓ Инвалидация работает при обновлении заказов

#### День 5: CORS для Production
- [ ] Обновить CORS конфигурацию в `main.py`
- [ ] Создать `.env.production` с примерами
- [ ] Добавить проверку `ALLOWED_ORIGINS` в production
- [ ] Протестировать с разными доменами
- [ ] Обновить документацию

**Критерии приёмки:**
- ✓ Production домены работают
- ✓ Localhost работает в dev режиме
- ✓ Preflight OPTIONS requests проходят

---

### Sprint 2: Инфраструктура (4 дня)

**Цель:** Упростить управление БД и расширить кеширование

#### День 6-7: Alembic миграции
- [ ] Установить `alembic==1.13.1`
- [ ] Инициализировать Alembic (`alembic init alembic`)
- [ ] Настроить `alembic/env.py`
- [ ] Создать начальную миграцию
- [ ] Протестировать upgrade/downgrade
- [ ] Создать CI/CD workflow для миграций
- [ ] Документировать процесс в README

**Критерии приёмки:**
- ✓ Все модели покрыты миграциями
- ✓ `alembic upgrade head` работает
- ✓ `alembic downgrade -1` работает
- ✓ CI проверяет pending migrations

#### День 8: Расширенное кеширование
- [ ] Кеширование списка заказов (`/orders`)
- [ ] Кеширование деталей заказа (`/order/{order_number}`)
- [ ] Кеширование статистики пользователя
- [ ] Оптимизация TTL для разных типов данных
- [ ] Добавить endpoint для просмотра метрик кеша

**Критерии приёмки:**
- ✓ Все основные эндпоинты кешируются
- ✓ TTL настроены оптимально
- ✓ Метрики доступны через API

#### День 9: Адаптивный timeout для Ozon API
- [ ] Обновить `services/ozon.py` с адаптивным timeout
- [ ] Добавить custom exceptions (`OzonTimeoutError`, `OzonRateLimitError`)
- [ ] Реализовать улучшенную retry стратегию
- [ ] Создать `utils/metrics.py` для мониторинга
- [ ] Добавить настройки в `.env`

**Критерии приёмки:**
- ✓ Большие запросы используют LONG_TIMEOUT
- ✓ Retry работает для 429/5xx с backoff
- ✓ Метрики показывают снижение timeout'ов на 30%

---

### Sprint 3: Тестирование и документация (2 дня)

**Цель:** Убедиться в стабильности и задокументировать изменения

#### День 10: Интеграционные тесты
- [ ] Тесты rate limiting
- [ ] Тесты кеширования
- [ ] Тесты CORS
- [ ] Тесты Alembic миграций
- [ ] Нагрузочные тесты (100+ concurrent users)
- [ ] Тесты отказоустойчивости (Redis down, DB down)

**Критерии приёмки:**
- ✓ Все тесты проходят
- ✓ Coverage > 80%
- ✓ Нагрузка 100 RPS без ошибок

#### День 11: Документация
- [ ] Обновить README.md
- [ ] Создать DEPLOYMENT.md
- [ ] Создать MONITORING.md
- [ ] Обновить API документацию (Swagger)
- [ ] Создать troubleshooting guide
- [ ] Видео-демо для команды

**Критерии приёмки:**
- ✓ Новые члены команды могут развернуть проект за 30 минут
- ✓ Все новые фичи задокументированы
- ✓ Swagger актуален

---

## 📦 Детальная реализация

### 1️⃣ Rate Limiting (Приоритет P0)

#### Проблема
При большом количестве пользователей одновременные запросы к Ozon API приводят к 429 ошибкам и блокировке.

#### Решение
Многоуровневый rate limiting с Redis.

#### Архитектура
```
Request → Middleware → Rate Limiter → Redis → Allow/Deny
```

#### Файлы для создания

**1. `utils/rate_limiter.py`**
```python
import redis
import asyncio
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("uvicorn.error")

class RateLimiter:
    """
    Многоуровневый rate limiter для Ozon API.
    
    Лимиты:
    - Per-user: 10 запросов/минуту
    - Global: 100 запросов/минуту
    """
    
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.USER_LIMIT = int(os.getenv('RATE_LIMIT_PER_USER', '10'))
        self.GLOBAL_LIMIT = int(os.getenv('RATE_LIMIT_GLOBAL', '100'))
        self.WINDOW = 60  # секунд
        
    async def check_user_limit(self, user_id: int) -> bool:
        """Проверка лимита для пользователя."""
        key = f"rate_limit:user:{user_id}"
        count = self.redis.get(key)
        
        if count is None:
            self.redis.setex(key, self.WINDOW, 1)
            return True
        
        if int(count) >= self.USER_LIMIT:
            return False
            
        self.redis.incr(key)
        return True
    
    async def check_global_limit(self) -> bool:
        """Проверка глобального лимита."""
        key = "rate_limit:global"
        count = self.redis.get(key)
        
        if count is None:
            self.redis.setex(key, self.WINDOW, 1)
            return True
        
        if int(count) >= self.GLOBAL_LIMIT:
            return False
            
        self.redis.incr(key)
        return True
    
    async def wait_for_slot(self, user_id: int, max_wait: int = 30) -> bool:
        """Ожидание доступного слота."""
        start = datetime.now()
        
        while (datetime.now() - start).seconds < max_wait:
            if await self.check_user_limit(user_id):
                if await self.check_global_limit():
                    return True
            await asyncio.sleep(0.5)
        
        return False
```

**2. `middleware/rate_limit_middleware.py`**
```python
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from utils.rate_limiter import RateLimiter
from utils.auth import decode_token

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_url: str):
        super().__init__(app)
        self.limiter = RateLimiter(redis_url)
        
    async def dispatch(self, request: Request, call_next):
        # Пропускаем публичные эндпоинты
        if request.url.path in ["/ping", "/docs", "/openapi.json", "/auth/login", "/auth/register"]:
            return await call_next(request)
        
        # Извлекаем user_id из токена
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return await call_next(request)
        
        try:
            payload = decode_token(token)
            user_id = payload.get("sub")
            
            # Проверяем лимиты
            if not await self.limiter.wait_for_slot(user_id, max_wait=5):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "rate_limit_exceeded",
                        "message": "Слишком много запросов. Попробуйте позже.",
                        "retry_after": 60
                    }
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Rate limit check failed: {e}")
        
        response = await call_next(request)
        return response
```

**3. Интеграция в `main.py`**
```python
import os
from middleware.rate_limit_middleware import RateLimitMiddleware

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Добавляем middleware после CORS
app.add_middleware(RateLimitMiddleware, redis_url=REDIS_URL)
```

**4. Обновить `.env`**
```bash
# Redis
REDIS_URL=redis://localhost:6379/0

# Rate limiting
RATE_LIMIT_PER_USER=10
RATE_LIMIT_GLOBAL=100
RATE_LIMIT_WINDOW=60
```

**5. Тестирование: `scripts/test_rate_limit.py`**
```python
import asyncio
import httpx

async def test_rate_limit():
    """Тест превышения лимита."""
    base_url = "http://localhost:8080"
    
    # Логин
    async with httpx.AsyncClient() as client:
        login_resp = await client.post(
            f"{base_url}/auth/login",
            json={"email": "test@test.com", "password": "test123"}
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Делаем 15 запросов (лимит 10/мин)
        success_count = 0
        rate_limited = False
        
        for i in range(15):
            try:
                resp = await client.get(f"{base_url}/orders", headers=headers)
                
                if resp.status_code == 200:
                    success_count += 1
                    print(f"✓ Request {i+1}: 200 OK")
                elif resp.status_code == 429:
                    rate_limited = True
                    print(f"✗ Request {i+1}: 429 Rate Limited")
                    break
            except Exception as e:
                print(f"✗ Request {i+1}: Error - {e}")
        
        print(f"\n{'='*50}")
        print(f"Успешных запросов: {success_count}")
        print(f"Rate limit сработал: {'✅ ДА' if rate_limited else '❌ НЕТ'}")
        
        if rate_limited:
            print("\n✅ Rate limiting работает корректно!")
        else:
            print("\n⚠️  Rate limiting не сработал - проверьте настройки")

if __name__ == "__main__":
    asyncio.run(test_rate_limit())
```

#### Установка Redis

**Windows:**
```powershell
# Через Chocolatey
choco install redis-64

# Или через Docker
docker run -d -p 6379:6379 --name redis redis:7-alpine
```

**Linux/macOS:**
```bash
# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl start redis

# macOS
brew install redis
brew services start redis
```

---

### 2️⃣ Кеширование (Приоритет P1)

#### Проблема
Каждый запрос аналитики идёт в БД, что создаёт высокую нагрузку и медленные ответы.

#### Решение
Многоуровневое кеширование с Redis и автоматической инвалидацией.

#### Архитектура
```
Request → Check Cache → Hit? Yes → Return
                      → Hit? No → Query DB → Cache → Return
```

#### Файлы для создания

**1. `utils/cache_manager.py`**
```python
import json
import redis
from typing import Any, Optional
import hashlib
import logging

logger = logging.getLogger("uvicorn.error")

class CacheManager:
    """Менеджер кеширования с TTL."""
    
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=False)
        
        # TTL для разных типов данных (секунды)
        self.TTL = {
            "analytics": 300,      # 5 минут
            "orders_list": 60,     # 1 минута
            "order_detail": 600,   # 10 минут
            "user_stats": 1800,    # 30 минут
        }
    
    def _make_key(self, namespace: str, user_id: int, **params) -> str:
        """Генерация уникального ключа."""
        sorted_params = sorted(params.items())
        params_str = json.dumps(sorted_params, sort_keys=True)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
        return f"cache:{namespace}:u{user_id}:{params_hash}"
    
    async def get(self, namespace: str, user_id: int, **params) -> Optional[Any]:
        """Получение из кеша."""
        key = self._make_key(namespace, user_id, **params)
        
        try:
            value = self.redis.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(value)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache GET error: {e}")
            return None
    
    async def set(self, namespace: str, user_id: int, data: Any, **params):
        """Сохранение в кеш."""
        key = self._make_key(namespace, user_id, **params)
        ttl = self.TTL.get(namespace, 300)
        
        try:
            value = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.redis.setex(key, ttl, value)
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
        except Exception as e:
            logger.error(f"Cache SET error: {e}")
    
    async def invalidate_user(self, user_id: int, namespace: Optional[str] = None):
        """Инвалидация кеша пользователя."""
        pattern = f"cache:{namespace or '*'}:u{user_id}:*"
        
        try:
            keys = self.redis.keys(pattern)
            if keys:
                self.redis.delete(*keys)
                logger.info(f"Invalidated {len(keys)} keys for user {user_id}")
        except Exception as e:
            logger.error(f"Cache INVALIDATE error: {e}")
    
    def get_stats(self) -> dict:
        """Статистика кеша."""
        info = self.redis.info()
        return {
            "used_memory": info.get("used_memory_human"),
            "total_keys": self.redis.dbsize(),
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
        }
```

**2. `utils/cache_decorator.py`**
```python
from functools import wraps
from typing import Callable

def cached(namespace: str):
    """Декоратор для автоматического кеширования."""
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get('request')
            current_user = kwargs.get('current_user')
            
            if not current_user or not request:
                return await func(*args, **kwargs)
            
            cache = request.app.state.cache
            user_id = current_user.id
            
            # Параметры для ключа кеша
            cache_params = {
                k: v for k, v in kwargs.items()
                if k not in ['request', 'db', 'current_user']
            }
            
            # Проверяем кеш
            cached_data = await cache.get(namespace, user_id, **cache_params)
            if cached_data is not None:
                return cached_data
            
            # Вызываем функцию
            result = await func(*args, **kwargs)
            
            # Кешируем результат
            await cache.set(namespace, user_id, result, **cache_params)
            
            return result
        
        return wrapper
    return decorator
```

**3. Применить к `routes/analytics.py`**
```python
from fastapi import Request
from utils.cache_decorator import cached

@router.get("/sales_today")
@cached(namespace="analytics")
async def sales_today(
    request: Request,
    since: str | None = None,
    to: str | None = None,
    tz_offset_hours: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Существующая логика без изменений
    ...
```

**4. Инвалидация в `services/enrichment.py`**
```python
async def enrich_posting_from_ozon(posting_number: str, user: User, db: Session):
    # ... существующая логика ...
    
    db.commit()
    
    # Инвалидация кеша
    cache = getattr(db, '_cache', None)
    if cache:
        await cache.invalidate_user(user.id, "analytics")
        await cache.invalidate_user(user.id, "orders_list")
    
    return result
```

**5. Интеграция в `main.py`**
```python
from utils.cache_manager import CacheManager

@app.on_event("startup")
async def startup_event():
    # Инициализация кеша
    app.state.cache = CacheManager(REDIS_URL)
    logger.info("Cache manager initialized")
    
    # Остальное без изменений
    ...

@app.get("/cache/stats")
async def cache_stats(current_user: User = Depends(get_current_user)):
    """Статистика кеша (только для авторизованных)."""
    return app.state.cache.get_stats()
```

---

### 3️⃣ CORS для Production (Приоритет P1)

#### Проблема
CORS настроен только для localhost, production деплой невозможен.

#### Решение
Окружение-зависимые CORS настройки.

#### Реализация в `main.py`

```python
import os
from fastapi.middleware.cors import CORSMiddleware

# Окружение
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOWED_ORIGINS_STR = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS_STR.split(",") if o.strip()]

# CORS
if ENVIRONMENT == "development":
    logger.info("🔧 CORS: Development mode (localhost allowed)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:54321",
            "http://127.0.0.1:54321",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ],
        allow_origin_regex=r"http://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
elif ENVIRONMENT == "production":
    if not ALLOWED_ORIGINS:
        raise ValueError("❌ ALLOWED_ORIGINS must be set in production!")
    
    logger.info(f"🔒 CORS: Production mode ({len(ALLOWED_ORIGINS)} origins allowed)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=3600,
    )
else:
    raise ValueError(f"❌ Unknown ENVIRONMENT: {ENVIRONMENT}")
```

#### Создать `.env.production`

```bash
# Production configuration
ENVIRONMENT=production
ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com

DATABASE_URL=postgresql://ozonuser:strong_password@production-db:5432/ozondb
REDIS_URL=redis://production-redis:6379/0

# Security (НОВЫЕ КЛЮЧИ для prod!)
ENCRYPTION_KEY=<GENERATE_NEW_KEY>
JWT_SECRET_KEY=<GENERATE_NEW_KEY>
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080

# Более строгие лимиты
RATE_LIMIT_PER_USER=5
RATE_LIMIT_GLOBAL=50

# Production tuning
ENRICH_CONCURRENCY=2
SYNC_INTERVAL_SECONDS=600

# Logging
LOG_LEVEL=WARNING
LOG_OZON_REQUESTS=false
```

---

### 4️⃣ Alembic миграции (Приоритет P2)

#### Проблема
Схема БД обновляется вручную, нет истории изменений и возможности rollback.

#### Решение
Внедрить Alembic для управления версиями БД.

#### Установка
```bash
pip install alembic==1.13.1
alembic init alembic
```

#### Настройка `alembic/env.py`

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
from dotenv import load_dotenv

load_dotenv()

# Импорт всех моделей
from db.database import Base
from db.database import (
    User, OzonCredential, Order, OrderHeader, 
    OrderPosting, OrderProduct, Cost, SyncStatus
)

config = context.config
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

#### Workflow

```bash
# 1. Создать миграцию
alembic revision --autogenerate -m "Add new field to User"

# 2. Проверить сгенерированный файл в alembic/versions/

# 3. Применить
alembic upgrade head

# 4. Откат (если нужно)
alembic downgrade -1

# 5. История
alembic history

# 6. Текущая версия
alembic current
```

#### CI/CD: `.github/workflows/migrations.yml`

```yaml
name: Database Migrations

on:
  push:
    branches: [main, develop]

jobs:
  check-migrations:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Check pending migrations
        run: alembic check
      
      - name: Apply migrations (staging)
        if: github.ref == 'refs/heads/develop'
        env:
          DATABASE_URL: ${{ secrets.STAGING_DATABASE_URL }}
        run: alembic upgrade head
```

---

### 5️⃣ Адаптивный Timeout (Приоритет P3)

#### Проблема
Ozon API медленный, 60s timeout иногда не хватает для больших запросов.

#### Решение
Адаптивный timeout + улучшенная retry стратегия.

#### Обновить `services/ozon.py`

```python
import os
import logging
import httpx
import asyncio
from typing import Optional

logger = logging.getLogger("uvicorn.error")

# Гибкие настройки
DEFAULT_TIMEOUT = int(os.getenv('OZON_DEFAULT_TIMEOUT', '60'))
LONG_TIMEOUT = int(os.getenv('OZON_LONG_TIMEOUT', '120'))
MAX_RETRIES = int(os.getenv('OZON_MAX_RETRIES', '3'))
RETRY_BACKOFF = float(os.getenv('OZON_RETRY_BACKOFF_SECONDS', '2.0'))

class OzonAPIError(Exception):
    """Базовое исключение."""
    pass

class OzonTimeoutError(OzonAPIError):
    """Timeout."""
    pass

class OzonRateLimitError(OzonAPIError):
    """429 Rate limit."""
    pass

async def ozon_fbo_list_async(
    client_id: str,
    api_key: str,
    filter_dict: dict,
    limit: int,
    offset: int,
    with_flags: dict,
    timeout: Optional[int] = None
):
    """
    Асинхронный запрос к Ozon с адаптивным timeout.
    """
    url = f"{BASE_URL}/v2/posting/fbo/list"
    body = {
        "dir": "ASC",
        "filter": filter_dict,
        "limit": limit,
        "offset": offset,
        "translit": True,
        "with": with_flags or {"analytics_data": True, "financial_data": True},
    }
    
    headers = _get_headers(client_id, api_key)
    
    # Адаптивный timeout
    if limit > 100:
        actual_timeout = timeout or LONG_TIMEOUT
        logger.debug(f"Large request (limit={limit}), using LONG_TIMEOUT={actual_timeout}s")
    else:
        actual_timeout = timeout or DEFAULT_TIMEOUT
    
    attempt = 0
    last_error = None
    
    while attempt <= MAX_RETRIES:
        try:
            async with httpx.AsyncClient() as client:
                logger.debug(f"Ozon request: timeout={actual_timeout}s, attempt={attempt+1}/{MAX_RETRIES+1}")
                
                r = await client.post(url, headers=headers, json=body, timeout=actual_timeout)
                r.raise_for_status()
                return r.json()
                
        except httpx.TimeoutException:
            last_error = OzonTimeoutError(f"Timeout after {actual_timeout}s")
            logger.warning(f"⏱️  Ozon timeout (attempt {attempt+1})")
            
        except httpx.HTTPError as e:
            status = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            
            if status == 401:
                logger.error("❌ Ozon Auth Failed")
                raise
            
            if status == 429:
                last_error = OzonRateLimitError("Rate limit exceeded")
                wait = RETRY_BACKOFF * (attempt + 1) * 2
                logger.warning(f"🚦 Ozon 429, waiting {wait}s")
                await asyncio.sleep(wait)
                attempt += 1
                continue
            
            retryable = status in (500, 502, 503, 504)
            if retryable and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * (attempt + 1)
                logger.warning(f"⚠️  Ozon {status}, retry in {wait}s")
                await asyncio.sleep(wait)
                attempt += 1
                continue
            
            last_error = e
        
        attempt += 1
    
    logger.error(f"❌ Ozon request failed after {MAX_RETRIES+1} attempts")
    raise last_error or OzonAPIError("Unknown error")
```

#### Обновить `.env`

```bash
# Ozon API настройки
OZON_DEFAULT_TIMEOUT=60
OZON_LONG_TIMEOUT=120
OZON_MAX_RETRIES=3
OZON_RETRY_BACKOFF_SECONDS=2.0
```

#### Мониторинг: `utils/ozon_metrics.py`

```python
from collections import defaultdict
from datetime import datetime

class OzonMetrics:
    """Метрики Ozon API."""
    
    def __init__(self):
        self.timeouts = defaultdict(int)
        self.retries = defaultdict(int)
        self.total = 0
        self.errors = defaultdict(int)
    
    def record_timeout(self, endpoint: str):
        self.timeouts[endpoint] += 1
    
    def record_retry(self, endpoint: str):
        self.retries[endpoint] += 1
    
    def record_error(self, endpoint: str, error_type: str):
        self.errors[f"{endpoint}:{error_type}"] += 1
    
    def record_request(self):
        self.total += 1
    
    def get_stats(self) -> dict:
        timeout_rate = sum(self.timeouts.values()) / max(self.total, 1)
        retry_rate = sum(self.retries.values()) / max(self.total, 1)
        
        return {
            "total_requests": self.total,
            "timeouts": dict(self.timeouts),
            "timeout_rate": f"{timeout_rate:.2%}",
            "retries": dict(self.retries),
            "retry_rate": f"{retry_rate:.2%}",
            "errors": dict(self.errors),
        }

# Глобальный экземпляр
ozon_metrics = OzonMetrics()
```

---

## 📊 Метрики успеха

### Количественные KPI

| Метрика | Сейчас | Цель | Метод измерения |
|---------|--------|------|-----------------|
| Cache Hit Rate | 0% | >60% | Redis INFO keyspace_hits/misses |
| Avg Response Time (analytics) | 500ms | <100ms | FastAPI middleware timing |
| Rate Limit Violations | N/A | 0 | 429 responses per day |
| Ozon Timeout Rate | ~5% | <2% | ozon_metrics.get_stats() |
| Database Load (QPS) | 50 | <20 | PostgreSQL stats |

### Качественные критерии

- [ ] Новый разработчик может развернуть проект за 30 минут
- [ ] Production деплой работает без ошибок CORS
- [ ] Миграции БД проходят без downtime
- [ ] Документация актуальна и полная
- [ ] Мониторинг показывает все ключевые метрики

---

## 🧪 Чек-лист перед релизом

### Pre-release (за неделю до релиза)

- [ ] Все задачи Sprint 1-3 выполнены
- [ ] Code review пройден
- [ ] Unit тесты покрытие >80%
- [ ] Интеграционные тесты все зелёные
- [ ] Нагрузочное тестирование пройдено (100 RPS)
- [ ] Документация обновлена
- [ ] Changelog подготовлен

### Release Day

- [ ] Backup production БД
- [ ] Применить Alembic миграции на staging
- [ ] Smoke tests на staging
- [ ] Deploy на production (blue-green)
- [ ] Применить миграции на production
- [ ] Smoke tests на production
- [ ] Мониторинг показывает зелёное
- [ ] Rollback план готов

### Post-release (первая неделя)

- [ ] Мониторинг метрик ежедневно
- [ ] No critical bugs
- [ ] Performance в пределах нормы
- [ ] User feedback собран
- [ ] Retrospective проведена

---

## 📚 Полезные команды

### Development

```bash
# Запуск с hot-reload
uvicorn main:app --reload --host 127.0.0.1 --port 8080

# Проверка линтером
flake8 . --max-line-length=120

# Форматирование
black . --line-length=120

# Типы
mypy . --ignore-missing-imports
```

### Redis

```bash
# Запуск Redis
redis-server

# CLI
redis-cli

# Очистка кеша
redis-cli FLUSHDB

# Статистика
redis-cli INFO stats
```

### Alembic

```bash
# Создать миграцию
alembic revision --autogenerate -m "Description"

# Применить
alembic upgrade head

# Откат на 1 версию
alembic downgrade -1

# История
alembic history --verbose

# Текущая версия
alembic current
```

### Testing

```bash
# Все тесты
pytest

# С покрытием
pytest --cov=. --cov-report=html

# Конкретный тест
pytest tests/test_rate_limit.py -v

# Нагрузочное тестирование
locust -f tests/load_test.py --host=http://localhost:8080
```

### Docker

```bash
# Сборка
docker-compose build

# Запуск
docker-compose up -d

# Логи
docker-compose logs -f backend

# Остановка
docker-compose down
```

---

## 🔗 Связанные документы

- [README.md](README.md) — Основная документация
- [MIGRATION_TO_POSTGRES.md](MIGRATION_TO_POSTGRES.md) — Миграция БД
- [FLUTTER_SAAS_ARCHITECTURE.md](FLUTTER_SAAS_ARCHITECTURE.md) — Flutter архитектура
- [CHANGELOG.md](CHANGELOG.md) — История изменений
- [DEPLOYMENT.md](DEPLOYMENT.md) — Инструкции по деплою (TODO)
- [MONITORING.md](MONITORING.md) — Мониторинг и алерты (TODO)

---

## 📝 Changelog

### [Unreleased]
- Rate limiting с Redis
- Многоуровневое кеширование
- CORS для production
- Alembic миграции
- Адаптивный timeout для Ozon API

### [1.0.1] - 2026-01-02
- Миграция на httpx
- Рефакторизация main.py
- SaaS архитектура с мультитенантностью
- JWT аутентификация
- Шифрование credentials

---

**Последнее обновление:** 13 февраля 2026 г.  
**Автор:** OzonAPIHub Team  
**Статус:** 📋 In Planning
