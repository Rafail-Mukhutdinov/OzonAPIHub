"""
Модуль конфигурации логирования.
Настраивает запись логов в файлы и консоль.
Реализует концепцию "Изолированных логов пользователей": каждое действие конкретного
пользователя пишется в его персональный файл, что упрощает отладку (debugging).
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

# Создаем структуру папок для хранения логов
LOG_DIR = "logs"
USER_LOG_DIR = os.path.join(LOG_DIR, "users") # Папка для логов отдельных пользователей
os.makedirs(USER_LOG_DIR, exist_ok=True)

# Определяем уровень логирования (по умолчанию INFO)
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
_lvl = getattr(logging, LOG_LEVEL, logging.INFO)

# Единый формат записи для всего приложения
# Пример: [2023-10-27 12:00:00] INFO    [OzonAPIHub] Сообщение
LOG_FORMAT = "[%(asctime)s] %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 1. Настройка ОБЩЕГО логгера приложения (app.log)
# Используем RotatingFileHandler, чтобы файлы не разрастались бесконечно.
# При достижении 5 МБ создается новый файл, хранится максимум 5 старых копий.
app_log_path = os.path.join(LOG_DIR, "app.log")
app_handler = RotatingFileHandler(
    app_log_path,
    maxBytes=5*1024*1024,
    backupCount=5,
    encoding='utf-8'
)
app_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

# Глобальная настройка logging
logging.basicConfig(
    level=_lvl,
    handlers=[
        app_handler,
        logging.StreamHandler() # Вывод в консоль (Stdout), нужен для Docker/Heroku
    ]
)

# Главный объект логгера для импорта в другие модули
logger = logging.getLogger("OzonAPIHub")

# Отключаем лишний шум от сторонних библиотек (httpx, и т.д.)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

def get_user_logger(user_id: int):
    """
    Создает или возвращает логгер, привязанный к конкретному ID пользователя.
    Логи будут писаться в файл: logs/users/user_1.log
    """
    logger_name = f"user_{user_id}"
    u_logger = logging.getLogger(logger_name)

    # Настраиваем обработчик, если он еще не добавлен (чтобы не дублировать записи)
    if not u_logger.hasHandlers():
        user_log_path = os.path.join(USER_LOG_DIR, f"user_{user_id}.log")
        # Лимиты для пользовательских логов поменьше (2МБ)
        handler = RotatingFileHandler(user_log_path, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        u_logger.addHandler(handler)
        u_logger.setLevel(logging.INFO)
        # propogate=False отключает передачу лога наверх (в app.log),
        # чтобы общий лог не забивался деталями синхронизации каждого пользователя.
        u_logger.propagate = False

    return u_logger

def log_user_event(user_id: int, message: str, level: str = "info"):
    """
    Удобная функция-обертка для логирования событий пользователя.
    Именно этот метод используется во всех сервисах и эндпоинтах.

    Args:
        user_id: ID пользователя из БД.
        message: Текст сообщения.
        level: Уровень (info, warning, error, debug).
    """
    u_logger = get_user_logger(user_id)
    # Динамически получаем метод логгера (например, u_logger.info или u_logger.error)
    method = getattr(u_logger, level.lower(), u_logger.info)
    method(message)
