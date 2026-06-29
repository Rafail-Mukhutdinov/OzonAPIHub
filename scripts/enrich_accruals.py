#!/usr/bin/env python3
"""
Скрипт для загрузки детализированных транзакций (accruals) за период
"""
import asyncio
import sys
from datetime import datetime, timedelta
from db.database import SessionLocal
from services.enrichment import enrich_accruals_from_ozon

async def enrich_accruals_range(user_id: int, start_date_str: str, end_date_str: str = None):
    """
    start_date_str: "2026-06-01"
    """
    if not end_date_str:
        end_date_str = start_date_str
        
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
    
    current_dt = start_dt
    db = SessionLocal()
    
    try:
        while current_dt <= end_dt:
            date_s = current_dt.strftime("%Y-%m-%d")
            print(f"Syncing accruals for {date_s}...", end="", flush=True)
            
            result = await enrich_accruals_from_ozon(user_id, date_s, db)
            
            if result.get("status") == "ok":
                print(f" ✓ Synced: {result.get('synced')}")
            else:
                print(f" ✗ Error: {result.get('detail')}")
                
            current_dt += timedelta(days=1)
            
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python enrich_accruals.py <user_id> <start_date> [end_date]")
        print("Example: python enrich_accruals.py 2 2026-06-01 2026-06-06")
        sys.exit(1)
    
    u_id = int(sys.argv[1])
    s_date = sys.argv[2]
    e_date = sys.argv[3] if len(sys.argv) > 3 else None
    
    asyncio.run(enrich_accruals_range(u_id, s_date, e_date))
