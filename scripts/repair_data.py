import asyncio
import os
import sys
from datetime import datetime

# Настройка путей
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import SessionLocal, User, OzonAccrual, OzonCredential
from services.enrichment import enrich_accruals_from_ozon
from utils.encryption import decrypt_credential

async def repair():
    db = SessionLocal()
    user = db.query(User).first()
    if not user:
        print("Пользователь не найден")
        return
        
    print(f"Пользователь: {user.email}")
    
    # Даты для исправления
    dates_to_repair = ["2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30", "2026-07-01"]
    
    for date_str in dates_to_repair:
        print(f"Очистка и перекачка данных за: {date_str}...")
        
        # 1. Удаляем старые данные
        acc_date = datetime.strptime(date_str, "%Y-%m-%d")
        deleted = db.query(OzonAccrual).filter(
            OzonAccrual.user_id == user.id,
            OzonAccrual.date == acc_date
        ).delete()
        db.commit()
        print(f"  Удалено {deleted} старых записей.")
        
        # 2. Загружаем заново через штатную функцию (она внутри использует новый код с quantity)
        try:
            from services.ozon import init_http_client, close_http_client
            init_http_client()
            await enrich_accruals_from_ozon(user.id, date_str, db)
            await close_http_client()
            print(f"  Успешно обновлено для {date_str}")
        except Exception as e:
            print(f"  Ошибка при обработке {date_str}: {e}")
        
    db.close()

if __name__ == "__main__":
    asyncio.run(repair())
