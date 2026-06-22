"""
Конфигурация ограничителя частоты запросов (Rate Limiter).
Используется для защиты API от перегрузки и парсинга (scraping).
Позволяет задавать лимиты как глобально, так и для отдельных пользователей.
"""

import os
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

# URL хранилища для счетчиков лимитов.
# В продакшене рекомендуется Redis, чтобы лимиты работали между рестартами сервера.
REDIS_URL = os.getenv("REDIS_URL", "memory://")

def get_real_ip(request: Request) -> str:
    """
    Извлекает реальный IP пользователя, даже если он за прокси (Nginx).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Берем первый адрес в списке (самый первый клиент)
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)

def get_user_id_or_ip(request: Request) -> str:
    """
    Функция определения уникального ключа клиента.
    """
    user = getattr(request.state, "user", None)
    if user:
        return f"user:{user.id}"
    return get_real_ip(request)

# Инициализируем Limiter
limiter = Limiter(
    key_func=get_user_id_or_ip,
    storage_uri=REDIS_URL,
    default_limits=[os.getenv("RATE_LIMIT_GLOBAL", "200/minute")]
)
