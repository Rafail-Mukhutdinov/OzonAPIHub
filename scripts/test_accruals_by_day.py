"""
Тестовый скрипт для поиска расхождений себестоимости.
Ищет все транзакции, которые Озон Банк может считать продажами.
"""

import sys
import os
import asyncio
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import SessionLocal, User, OzonCredential, OrderProduct
from utils.encryption import decrypt_credential
from services.ozon import ozon_accruals_by_day_async, init_http_client, close_http_client
from services.costs import get_product_cost


async def fetch_all_accruals(client_id: str, api_key: str, date_str: str):
    all_accruals = []
    last_id = ""
    while True:
        response = await ozon_accruals_by_day_async(client_id, api_key, date_str, last_id)
        accruals = response.get("accruals") or []
        if not accruals: break
        all_accruals.extend(accruals)
        last_id = response.get("last_id")
        if not last_id: break
    return all_accruals


def parse_amount(val) -> float:
    if val is None: return 0.0
    if isinstance(val, dict): return float(val.get("amount") or 0)
    try: return float(val)
    except: return 0.0


def analyze_accruals(accruals: list, db: SessionLocal, user_id: int, date_str: str):
    total_cost_price = 0.0
    target_date = datetime.strptime(date_str, "%Y-%m-%d")
    
    sku_details = defaultdict(lambda: {"qty": 0, "cost": 0.0, "offer_id": "", "rev": 0.0})
    
    # Загружаем артикулы
    all_skus = set()
    for acc in accruals:
        if acc.get("posting"):
            for p in acc["posting"].get("products", []): all_skus.add(int(p["sku"]))
        if acc.get("item_fees"):
            for f in acc["item_fees"].get("fees", []): all_skus.add(int(f["sku"]))
    
    sku_to_offer = {}
    if all_skus:
        db_items = db.query(OrderProduct.sku, OrderProduct.offer_id).filter(
            OrderProduct.user_id == user_id, OrderProduct.sku.in_(list(all_skus))
        ).distinct().all()
        sku_to_offer = {int(r[0]): r[1] for r in db_items}

    for acc in accruals:
        cat = acc.get("accrued_category")
        total_amt = parse_amount(acc.get("total_amount"))
        
        if cat == "POSTING" and acc.get("posting"):
            for prod in acc["posting"].get("products", []):
                sku = int(prod.get("sku") or 0)
                qty = int(prod.get("quantity") or 1)
                comm = prod.get("commission") or {}
                
                sku_details[sku]["offer_id"] = prod.get("offer_id") or sku_to_offer.get(sku, str(sku))
                
                # ЛОГИКА ОПРЕДЕЛЕНИЯ ПРОДАЖИ:
                # 1. Есть явный sale_amount > 0
                # 2. Или итоговая сумма транзакции за товар положительная (бывает при компенсациях)
                sale_amt = parse_amount(comm.get("sale_amount"))
                
                is_sale = sale_amt > 0
                if not is_sale and total_amt > 0 and prod == acc["posting"]["products"][0]:
                    # Если в транзакции нет sale_amount, но есть выплата (>0) - считаем продажей
                    is_sale = True

                if is_sale:
                    cp = get_product_cost(db, user_id, sku, target_date)
                    sku_details[sku]["qty"] += qty
                    sku_details[sku]["cost"] += cp * qty
                    sku_details[sku]["rev"] += (sale_amt or total_amt) * qty
                    total_cost_price += cp * qty
                elif sale_amt < 0:
                    cp = get_product_cost(db, user_id, sku, target_date)
                    sku_details[sku]["qty"] -= qty
                    sku_details[sku]["cost"] -= cp * qty
                    total_cost_price -= cp * qty

        elif cat == "ITEM":
            # Проверяем ITEM на наличие выплат (компенсации за утерю и т.д. Озон банк считает продажей)
            fee_item = (acc.get("item_fees") or {}).get("fees", [{}])[0]
            sku = int(fee_item.get("sku") or 0)
            if sku and total_amt > 0:
                cp = get_product_cost(db, user_id, sku, target_date)
                sku_details[sku]["offer_id"] = sku_to_offer.get(sku, str(sku))
                sku_details[sku]["qty"] += 1
                sku_details[sku]["cost"] += cp
                total_cost_price += cp

    print(f"\n--- ОТЧЁТ ЗА {date_str} ---")
    print(f"Итого себестоимость: {total_cost_price:10.2f}")
    print(f"{'Артикул':<15} {'SKU':<12} {'Кол-во':>6} {'Итого Себ.':>12}")
    print("-" * 50)
    for s, d in sorted(sku_details.items(), key=lambda x: -x[1]["cost"]):
        if d["qty"] == 0: continue
        print(f"{str(d['offer_id']):<15} {s:<12} {d['qty']:>6} {d['cost']:>12.2f}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="Дата YYYY-MM-DD")
    args = parser.parse_args()
    db = SessionLocal()
    user = db.query(User).first()
    cred = db.query(OzonCredential).filter(OzonCredential.user_id == user.id, OzonCredential.is_active == True).first()
    client_id, api_key = decrypt_credential(cred.client_id_encrypted), decrypt_credential(cred.api_key_encrypted)
    init_http_client()
    try:
        accruals = await fetch_all_accruals(client_id, api_key, args.date)
        analyze_accruals(accruals, db, user.id, args.date)
    finally:
        await close_http_client()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
