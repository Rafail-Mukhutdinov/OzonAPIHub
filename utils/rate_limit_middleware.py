from fastapi import FastAPI
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from utils.rate_limiter import limiter

def setup_rate_limiting(app: FastAPI):
    """
    Подключает Rate Limiting (SlowAPI) к FastAPI приложению.
    """
    # Добавляем limiter в state приложения
    app.state.limiter = limiter
    
    # Регистрируем обработчик ошибки 429 Too Many Requests, чтобы возвращать JSON
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    # Добавляем middleware, который будет проверять лимиты на каждом запросе
    app.add_middleware(SlowAPIMiddleware)
    
    return app