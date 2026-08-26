"""
Модуль общих вспомогательных утилит.
Содержит функции, которые используются в нескольких местах проекта и не имеют
узкой специализации.
"""

from datetime import datetime, timedelta, timezone
from typing import Union

def get_now_utc() -> datetime:
    """
    Возвращает текущее время в UTC как наивный объект datetime (без tzinfo).
    Это стандарт проекта для хранения дат в БД и их сравнения.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

def parse_ozon_datetime(value: Union[str, datetime, None]) -> Union[datetime, None]:
    """
    Универсальный парсинг даты из разных форматов Ozon API.
    Поддерживает:
    - 2025-06-15T00:00:00Z
    - 2025-06-15T00:00:00.000Z
    - 2025-06-15T00:00:00+03:00
    - 2025-06-15 00:00:00
    - datetime объекты (наивные считаются UTC)
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        # Убираем Z и микросекунды для простого парсинга, если нужно
        # Но fromisoformat в Python 3.11+ хорошо справляется с Z
        clean_value = value.replace('Z', '+00:00')
        dt = datetime.fromisoformat(clean_value)
        # Если дата наивная, считаем её UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        # Фоллбек на ручной парсинг простых форматов
        formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
        for fmt in formats:
            try:
                dt = datetime.strptime(value.split('.')[0].split('+')[0].strip(), fmt)
                return dt.replace(tzinfo=timezone.utc)
            except:
                continue
    return None

def to_msk(dt_or_str: Union[str, datetime, None], offset_hours: int = 3) -> Union[datetime, None]:
    """
    Переводит UTC datetime или строку в местное время (по умолчанию MSK UTC+3).
    
    ВАЖНО: Ozon API работает преимущественно в московском часовом поясе (UTC+3). 
    Финансовые отчеты, аналитика и логистические метрики в Ozon привязаны к МСК. 
    Поэтому для корректного отображения данных пользователю и запросов к API 
    мы конвертируем системное UTC-время в UTC+3.
    """
    dt = parse_ozon_datetime(dt_or_str)
    if dt is None:
        return None
    return dt.astimezone(timezone(timedelta(hours=offset_hours))).replace(tzinfo=None)

def to_msk_date(dt_or_str: Union[str, datetime, None], offset_hours: int = 3) -> str:
    """Извлекает дату ГГГГ-ММ-ДД по местному времени."""
    dt_local = to_msk(dt_or_str, offset_hours)
    if dt_local is None:
        return ""
    return dt_local.strftime("%Y-%m-%d")

def valid_posting_number(pn: str | None) -> bool:
    """
    Валидация номера отправления (posting_number).
    Проверяет, является ли номер корректным идентификатором Ozon FBO.
    Исключает тестовые данные и некорректные строки.

    Примеры валидных номеров: '12345678-0001', '0987654321-2'
    """
    if not pn:
        return False

    # Игнорируем тестовые отправления
    if pn.upper().startswith('TEST-POSTING'):
        return False

    # В номерах Ozon всегда есть дефис (разделитель заказа и подзаказа)
    if '-' not in pn:
        return False

    # Проверяем, что после последнего дефиса идут только цифры
    suffix = pn.split('-')[-1]
    return suffix.isdigit()

def normalize_iso(val: Union[str, datetime, None]) -> str:
    """Приводит дату к ISO-строке с Z на конце для БД."""
    dt = parse_ozon_datetime(val)
    if not dt:
        raise ValueError(f"Некорректный формат даты: {val}")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
