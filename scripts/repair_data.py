"""
Скрипт для исправления (перекачки) данных о начислениях за конкретные даты.

Назначение:
    - Используется администратором, если за определенные дни данные в БД оказались 
      некорректными (например, из-за бага в старой версии парсера).
    - Скрипт полностью удаляет записи за дату и скачивает их заново.

Логика работы:
    1. Итерируется по списку 'dates_to_repair'.
    2. Для каждой даты выполняет SQL DELETE в таблице 'ozon_accruals'.
    3. Вызывает 'enrich_accruals_from_ozon' для повторной загрузки чистых данных из API.

Ключевые переменные:
    - dates_to_repair: Список дат, требующих исправления.
    - user: Пользователь, чьи данные исправляются (по умолчанию берется первый из БД).
"""
import asyncio
import os
import sys
from datetime import datetime

# Настройка путей проекта
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import SessionLocal, User, OzonAccrual, OzonCredential
from services.enrichment import enrich_accruals_from_ozon
from utils.encryption import decrypt_credential

async def repair():
    """
    Основная процедура очистки и повторной загрузки данных.
    """
    db = SessionLocal()
    # Берем первого пользователя для упрощения (в SaaS логике здесь должен быть ввод ID)
    user = db.query(User).first()
    if not user:
        print("Пользователь не найден")
        return
        
    print(f"Исправление данных для пользователя: {user.email}")
    
    # Конкретные даты, в которых были замечены ошибки (например, неверное количество или суммы)
    dates_to_repair = ["2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30", "2026-07-01"]
    
    for date_str in dates_to_repair:
        print(f"Очистка и перекачка данных за: {date_str}...")
        
        # 1. Удаляем старые (ошибочные) данные из БД
        acc_date = datetime.strptime(date_str, "%Y-%m-%d")
        deleted = db.query(OzonAccrual).filter(
            OzonAccrual.user_id == user.id,
            OzonAccrual.date == acc_date
        ).delete()
        db.commit()
        print(f"  Удалено {deleted} старых записей.")
        
        # 2. Загружаем данные заново через штатную функцию обогащения
        try:
            from services.ozon import init_http_client, close_http_client
            init_http_client()
            # Эта функция выполнит запрос к Ozon API и заполнит таблицу актуальными данными
            await enrich_accruals_from_ozon(user.id, date_str, db)
            await close_http_client()
            print(f"  Успешно обновлено для {date_str}")
        except Exception as e:
            print(f"  Ошибка при обработке {date_str}: {e}")
        
    db.close()

if __name__ == "__main__":
    asyncio.run(repair())
