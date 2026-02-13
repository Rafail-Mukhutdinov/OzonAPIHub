#!/usr/bin/env python3
"""
Скрипт для обогащения всех постингов за конкретную дату
"""
import asyncio
import sys
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.database import SessionLocal, OrderPosting, User
from services.enrichment import enrich_posting_from_ozon

async def enrich_date_range(user_id: int, date_str: str):
    """
    Обогатить все постинги за конкретную дату (MSK)
    date_str: "2026-02-01"
    """
    from dateutil import parser
    
    # Парсим дату в MSK
    target_date = parser.parse(date_str)
    # Переводим в UTC: MSK = UTC+3, поэтому начало дня MSK это 21:00 UTC предыдущего дня
    start_utc = parser.parse(f"{date_str}T00:00:00+03:00").isoformat().replace('+03:00', 'Z')
    end_utc = parser.parse(f"{date_str}T23:59:59+03:00").isoformat().replace('+03:00', 'Z')
    
    print(f"Ищу постинги за {date_str} (MSK)")
    print(f"UTC range: {start_utc} to {end_utc}")
    
    db = SessionLocal()
    try:
        # Находим все постинги за эту дату
        postings = db.query(OrderPosting).filter(
            OrderPosting.user_id == user_id,
            OrderPosting.created_at >= start_utc,
            OrderPosting.created_at <= end_utc
        ).all()
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            print(f"User {user_id} not found")
            return
        
        print(f"Found {len(postings)} postings")
        
        for i, posting in enumerate(postings, 1):
            try:
                print(f"[{i}/{len(postings)}] Enriching {posting.posting_number}...", end="")
                result = await enrich_posting_from_ozon(posting.posting_number, user, db)
                print(f" ✓")
            except Exception as e:
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
