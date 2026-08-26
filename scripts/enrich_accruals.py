#!/usr/bin/env python3
"""
Скрипт для массовой загрузки финансовых транзакций (начислений/accruals) за период.

Назначение:
    - Позволяет администратору синхронизировать детализированные отчеты о начислениях за выбранные даты.
    - Актуально для получения точной прибыли (чистая сумма, комиссии, логистика) по каждому товару.

Логика работы:
    1. Проходит циклом от начальной даты до конечной (включительно).
    2. Для каждой даты вызывает сервис 'enrich_accruals_from_ozon'.
    3. Сервис запрашивает данные у Ozon API, парсит их и сохраняет в таблицу 'ozon_accruals'.

Ключевые переменные:
    - user_id: ID пользователя в системе.
    - start_date_str: Дата начала в формате ГГГГ-ММ-ДД.
    - end_date_str: Дата окончания (если не указана, берется только один день).
    - current_dt: Текущая дата в итерации цикла.
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

# Настройка путей для корректного импорта модулей из корня проекта
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Загрузка переменных окружения (настройки БД и т.д.)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import SessionLocal
from services.enrichment import enrich_accruals_from_ozon


async def enrich_accruals_range(user_id: int, start_date_str: str, end_date_str: str = None):
    """
    Функция синхронизации начислений за диапазон дат.
    
    Аргументы:
        user_id: ID пользователя.
        start_date_str: Начало периода (ГГГГ-ММ-ДД).
        end_date_str: Конец периода.
    """
    if not end_date_str:
        end_date_str = start_date_str

    # Преобразование строк в объекты datetime для работы цикла
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")

    current_dt = start_dt
    db = SessionLocal()

    try:
        # Цикл по дням в указанном интервале
        while current_dt <= end_dt:
            date_s = current_dt.strftime("%Y-%m-%d")
            print(f"Синхронизация начислений за {date_s}...", end="", flush=True)

            # Вызов сервисного метода получения данных от Ozon
            result = await enrich_accruals_from_ozon(user_id, date_s, db)

            if result.get("status") == "ok":
                # Вывод статистики по загруженным данным
                print(f" ОК: Синхронизировано {result.get('synced')} транзакций ({result.get('rows', 0)} строк)")
            else:
                print(f" ОШИБКА: {result.get('detail')}")

            # Переход к следующему дню
            current_dt += timedelta(days=1)

    finally:
        db.close()


if __name__ == "__main__":
    # Обработка аргументов командной строки
    if len(sys.argv) < 3:
        print("Использование: python enrich_accruals.py <user_id> <start_date> [end_date]")
        print("Пример: python enrich_accruals.py 2 2026-06-01 2026-06-06")
        sys.exit(1)

    u_id = int(sys.argv[1])
    s_date = sys.argv[2]
    e_date = sys.argv[3] if len(sys.argv) > 3 else None

    asyncio.run(enrich_accruals_range(u_id, s_date, e_date))
