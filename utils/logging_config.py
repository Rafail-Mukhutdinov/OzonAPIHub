import logging
import os
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

# Папки для логов
LOG_DIR = "logs"
USER_LOG_DIR = os.path.join(LOG_DIR, "users")
os.makedirs(USER_LOG_DIR, exist_ok=True)

# Настройки уровней
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
_lvl = getattr(logging, LOG_LEVEL, logging.INFO)

# Формат: [Дата] [Уровень] [Компонент] Сообщение
LOG_FORMAT = "[%(asctime)s] %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 1. Основной логгер приложения (app.log)
# Ограничение: 5МБ на файл, храним 5 последних копий
app_log_path = os.path.join(LOG_DIR, "app.log")
app_handler = RotatingFileHandler(app_log_path, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
app_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

logging.basicConfig(
    level=_lvl,
    handlers=[
        app_handler,
        logging.StreamHandler() # Дублируем в консоль для Docker
    ]
)

logger = logging.getLogger("OzonAPIHub")

def get_user_logger(user_id: int):
    """
    Создает изолированный логгер для пользователя.
    Путь: logs/users/user_1.log
    """
    logger_name = f"user_{user_id}"
    u_logger = logging.getLogger(logger_name)

    if not u_logger.hasHandlers():
        user_log_path = os.path.join(USER_LOG_DIR, f"user_{user_id}.log")
        # Для пользователей файлы поменьше: 2МБ, 3 копии
        handler = RotatingFileHandler(user_log_path, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        u_logger.addHandler(handler)
        u_logger.setLevel(logging.INFO)
        u_logger.propagate = False # Не дублировать в общий app.log

    return u_logger

def log_user_event(user_id: int, message: str, level: str = "info"):
    """Простой способ записать событие для пользователя."""
    u_logger = get_user_logger(user_id)
    method = getattr(u_logger, level.lower(), u_logger.info)
    method(message)
