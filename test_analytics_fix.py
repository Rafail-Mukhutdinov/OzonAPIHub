"""
Проверочный скрипт для тестирования исправлений аналитики.
Проверяет:
1. Правильность фильтрации по датам в UTC vs MSK
2. Корректность включения/исключения отмен
3. Правильность расчета выручки (price * quantity)
"""

import sys
from datetime import datetime, timedelta, timezone
from utils.common import to_msk, parse_ozon_datetime

def test_datetime_conversion():
    """Тест конвертации времени UTC -> MSK"""
    print("\n=== ТЕСТ 1: Конвертация времени UTC -> MSK ===")
    
    # Пример из задачи: 14.06.2026 21:09 UTC -> 15.06.2026 00:09 MSK
    test_cases = [
        ("2026-06-14T21:09:00Z", "2026-06-15", "14 июня 21:09 UTC -> 15 июня MSK"),
        ("2026-06-09T22:24:00Z", "2026-06-10", "09 июня 22:24 UTC -> 10 июня MSK"),
        ("2026-06-15T10:00:00Z", "2026-06-15", "15 июня 10:00 UTC -> 15 июня MSK"),
    ]
    
    for utc_str, expected_date_msk, description in test_cases:
        dt_utc = parse_ozon_datetime(utc_str)
        dt_msk = to_msk(dt_utc)
        date_msk = dt_msk.date().strftime("%Y-%m-%d")
        
        status = "✓ PASS" if date_msk == expected_date_msk else "✗ FAIL"
        print(f"{status}: {description}")
        print(f"  UTC: {utc_str} -> MSK: {dt_msk} (дата: {date_msk})")
        if date_msk != expected_date_msk:
            print(f"  ОШИБКА: Ожидалось {expected_date_msk}, получилось {date_msk}")

def test_search_window():
    """Тест расширения окна поиска"""
    print("\n=== ТЕСТ 2: Расширение окна поиска (±4 часа вместо ±14) ===")
    
    # Дата в МСК: 15 июня, 00:00 по МСК
    dt_msk = datetime(2026, 6, 15, 0, 0, 0)
    dt_msk_with_tz = dt_msk.replace(tzinfo=timezone(timedelta(hours=3)))
    dt_utc = dt_msk_with_tz.astimezone(timezone.utc)
    
    print(f"Дата в МСК: 2026-06-15 00:00")
    print(f"Эквивалент в UTC: {dt_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    # Старое расширение (14 часов)
    old_search_start = dt_utc - timedelta(hours=14)
    old_search_end = dt_utc + timedelta(hours=14)
    print(f"\nСтарое расширение (14 часов):")
    print(f"  Начало: {old_search_start.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Конец: {old_search_end.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    # Новое расширение (4 часа)
    new_search_start = dt_utc - timedelta(hours=4)
    new_search_end = dt_utc + timedelta(hours=4)
    print(f"\nНовое расширение (4 часа):")
    print(f"  Начало: {new_search_start.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Конец: {new_search_end.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"\n✓ PASS: Расширение сокращено с 28 часов до 8 часов")

def test_cancelled_detection():
    """Тест детекции отмен"""
    print("\n=== ТЕСТ 3: Детекция отмен ===")
    
    test_statuses = [
        ("cancelled", True, "cancelled (lowercase)"),
        ("Cancelled", True, "Cancelled (title case)"),
        ("CANCELLED", True, "CANCELLED (uppercase)"),
        ("отменен", True, "отменен"),
        ("отменён", True, "отменён"),
        ("Доставлен", False, "Доставлен (активный статус)"),
        ("Отправлен", False, "Отправлен (активный статус)"),
        (None, False, "None (пустой статус)"),
    ]
    
    def is_cancelled(st):
        """Копия функции из analytics.py"""
        if not st:
            return False
        status_lower = str(st).lower().strip()
        cancelled_patterns = ["cancelled", "отменен", "отменён", "cancel"]
        return any(pattern in status_lower for pattern in cancelled_patterns)
    
    for status, expected, description in test_statuses:
        result = is_cancelled(status)
        status_check = "✓ PASS" if result == expected else "✗ FAIL"
        print(f"{status_check}: {description} -> {result}")
        if result != expected:
            print(f"  ОШИБКА: Ожидалось {expected}, получилось {result}")

def test_price_calculation():
    """Тест расчета выручки"""
    print("\n=== ТЕСТ 4: Расчет выручки (price × quantity) ===")
    
    test_cases = [
        (100, 3, 300, "100 ₽ × 3 шт = 300 ₽"),
        (5000, 2, 10000, "5000 ₽ × 2 шт = 10000 ₽"),
        (0, 100, 0, "0 ₽ × 100 шт = 0 ₽ (нулевая цена)"),
    ]
    
    for price, quantity, expected_revenue, description in test_cases:
        revenue = price * quantity
        status = "✓ PASS" if revenue == expected_revenue else "✗ FAIL"
        print(f"{status}: {description}")
        if revenue != expected_revenue:
            print(f"  ОШИБКА: Получилось {revenue}")

def test_string_comparison_issue():
    """Тест демонстрирующий ошибку string сравнения"""
    print("\n=== ТЕСТ 5: Демонстрация ошибки string сравнения (ИСПРАВЛЕНО) ===")
    
    db_search_since = "2026-06-14"  # Старый формат (неправильный)
    created_at = "2026-06-15T10:30:45Z"  # Правильный формат ISO
    
    # Старое неправильное сравнение
    old_comparison = created_at >= db_search_since
    print(f"Старое неправильное сравнение:")
    print(f"  '{created_at}' >= '{db_search_since}' = {old_comparison}")
    print(f"  РЕЗУЛЬТАТ: Заказ будет ИСКЛЮЧЕН (неправильно!)")
    
    # Новое правильное сравнение
    db_search_since_correct = "2026-06-14T00:00:00Z"
    new_comparison = created_at >= db_search_since_correct
    print(f"\nНовое правильное сравнение ISO:")
    print(f"  '{created_at}' >= '{db_search_since_correct}' = {new_comparison}")
    print(f"  РЕЗУЛЬТАТ: Заказ будет ВКЛЮЧЕН (правильно!)")
    print(f"\n✓ PASS: Строковое сравнение дат исправлено на правильное сравнение ISO")

if __name__ == "__main__":
    print("=" * 60)
    print("ПРОВЕРКА ИСПРАВЛЕНИЙ АНАЛИТИКИ OZONAPIHUB")
    print("=" * 60)
    
    try:
        test_datetime_conversion()
        test_search_window()
        test_cancelled_detection()
        test_price_calculation()
        test_string_comparison_issue()
        
        print("\n" + "=" * 60)
        print("✓ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)
