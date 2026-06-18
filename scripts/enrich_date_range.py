#!/usr/bin/env python3
"""
Скрипт для обогащения всех постингов за конкретную дату
"""
import asyncio
import sys
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.database import SessionLocal, OrderPosting, User, Order
from services.enrichment import enrich_posting_from_ozon

async def enrich_date_range(user_id: int, date_str: str):
    """
    Обогатить все постинги за конкретную дату (MSK)
    date_str: "2026-02-01"
    """
    from datetime import datetime, timedelta, timezone

    # Парсим дату в MSK (UTC+3) без сторонних библиотек
    try:
        y, m, d = map(int, date_str.split('-'))
        # Начало дня MSK (00:00:00+03:00)
        start_msk = datetime(y, m, d, 0, 0, 0, tzinfo=timezone(timedelta(hours=3)))
        # Конец дня MSK (23:59:59+03:00)
        end_msk = datetime(y, m, d, 23, 59, 59, tzinfo=timezone(timedelta(hours=3)))
    except Exception as e:
        print(f"Ошибка формата даты: {e}. Используйте ГГГГ-ММ-ДД")
        return

    # Переводим в UTC для поиска в БД
    start_utc = start_msk.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    end_utc = end_msk.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    print(f"Ищу постинги за {date_str} (MSK)")
    print(f"UTC range: {start_utc} to {end_utc}")
    
    db = SessionLocal()
    try:
        # 1. Сначала ищем в нормализованной таблице
        norm_postings = db.query(OrderPosting.posting_number).filter(
            OrderPosting.user_id == user_id,
            OrderPosting.created_at >= start_utc,
            OrderPosting.created_at <= end_utc
        ).all()

        # 2. Ищем в сырой таблице (чтобы найти те, что еще не нормализованы)
        raw_postings = db.query(Order.posting_number).filter(
            Order.user_id == user_id,
            Order.created_at >= start_utc,
            Order.created_at <= end_utc
        ).all()

        all_pns = sorted(set([p[0] for p in norm_postings] + [p[0] for p in raw_postings]))

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            print(f"User {user_id} not found")
            return
        
        print(f"Found {len(all_pns)} unique postings")
        
        for i, pn in enumerate(all_pns, 1):
            try:
                print(f"[{i}/{len(all_pns)}] Enriching {pn}...", end="")
                # Передаем user_id напрямую в новую версию функции, если она была обновлена,
                # или оставляем как было (зависит от версии enrichment.py)
                result = await enrich_posting_from_ozon(pn, user_id, db)
                if result.get("status") == "ok":
                    db.commit()
                    print(f" ✓")
                else:
                    db.rollback()
                    print(f" ✗ {result.get('status')}")
            except Exception as e:
                db.rollback()
                print(f" ✗ Error: {e}")
                
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python enrich_date_range.py <user_id> <date>")
        print("Example: python enrich_date_range.py 2 2026-02-01")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    date_str = sys.argv[2]
    
    asyncio.run(enrich_date_range(user_id, date_str))
