import sys
import os
import asyncio
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import SessionLocal, OzonCredential
from utils.encryption import decrypt_credential
from services.ozon import ozon_accruals_by_day_async, init_http_client, close_http_client

async def main():
    db = SessionLocal()
    cred = db.query(OzonCredential).first()
    client_id = decrypt_credential(cred.client_id_encrypted)
    api_key = decrypt_credential(cred.api_key_encrypted)
    
    date_str = "2026-07-01"
    target_sku = 3454933416
    
    print(f"Ищем SKU {target_sku} в данных за {date_str}...")
    init_http_client()
    
    accruals = []
    last_id = ""
    while True:
        res = await ozon_accruals_by_day_async(client_id, api_key, date_str, last_id)
        data = res.get("accruals") or []
        if not data: break
        accruals.extend(data)
        last_id = res.get("last_id")
        if not last_id: break

    found = False
    for acc in accruals:
        raw_str = str(acc)
        if str(target_sku) in raw_str:
            found = True
            print("\n--- НАЙДЕНА ТРАНЗАКЦИЯ ---")
            print(f"Категория: {acc.get('accrued_category')}")
            print(f"Сумма транзакции: {acc.get('total_amount')}")
            if acc.get("posting"):
                p = acc["posting"]
                print(f"Заказ: {p.get('posting_number')}")
                for prod in p.get("products", []):
                    if int(prod.get("sku") or 0) == target_sku:
                        print(f"  Товар в заказе: SKU={prod.get('sku')}, sale_amount={prod.get('commission', {}).get('sale_amount')}")
            if acc.get("item_fees"):
                print(f"Детали услуг: {acc.get('item_fees')}")

    if not found:
        print("\nТранзакций с таким SKU не найдено в API за этот день.")
    
    await close_http_client()
    db.close()

if __name__ == "__main__":
    asyncio.run(main())
