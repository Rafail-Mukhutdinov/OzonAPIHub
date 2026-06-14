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

def get_user_id_or_ip(request: Request) -> str:
    """
    Функция определения уникального ключа клиента.
    1. Если пользователь авторизован, ключом будет его ID (user:123).
    2. Если нет (регистрация/логин), ключом будет IP-адрес.
    """
    if hasattr(request.state, "user") and request.state.user:
        # Лимитируем по ID пользователя, чтобы смена IP не помогала обходить лимит
        return f"user:{request.state.user.id}"
    return get_remote_address(request)

# Инициализируем Limiter
limiter = Limiter(
    key_func=get_user_id_or_ip,
    storage_uri=REDIS_URL,
    # Лимит по умолчанию для всех эндпоинтов, если не указан специфичный
    default_limits=[os.getenv("RATE_LIMIT_GLOBAL", "100/minute")]
)
