#!/usr/bin/env python3
import sys
sys.path.insert(0, '/workspace')
from db.database import SessionLocal, OrderProduct, OrderPosting
from sqlalchemy import func

db = SessionLocal()

print("=== TOP товары по суммарному quantity ===")
results = db.query(
    OrderProduct.offer_id,
    OrderProduct.sku,
    OrderProduct.name,
    func.count(OrderProduct.id).label("total_records"),
    func.sum(OrderProduct.quantity).label("total_quantity")
).filter(OrderProduct.user_id == 2).group_by(
    OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name
).order_by(func.sum(OrderProduct.quantity).desc()).limit(10).all()

for r in results:
    print(f"offer_id={r.offer_id}, sku={r.sku}, records={r.total_records}, quantity={r.total_quantity}")
    print(f"  name: {r.name[:60]}")

print("\n=== Проверка на дубли: одинаковые (offer_id, posting_number) ===")
dupes = db.query(
    OrderProduct.offer_id,
    OrderProduct.posting_number,
    func.count(OrderProduct.id).label("cnt")
).filter(OrderProduct.user_id == 2).group_by(
    OrderProduct.offer_id, OrderProduct.posting_number
).filter(func.count(OrderProduct.id) > 1).limit(10).all()

if dupes:
    for r in dupes:
        print(f"offer_id={r.offer_id}, posting_number={r.posting_number}, count={r.cnt}")
else:
    print("Дублей не найдено")

print("\n=== Статистика по постингам ===")
posting_count = db.query(func.count(func.distinct(OrderProduct.posting_number))).filter(
    OrderProduct.user_id == 2
).scalar()
print(f"Всего уникальных posting_number: {posting_count}")

total_qty = db.query(func.sum(OrderProduct.quantity)).filter(
    OrderProduct.user_id == 2
).scalar()
print(f"Общее количество товаров: {total_qty}")

total_records = db.query(func.count(OrderProduct.id)).filter(
    OrderProduct.user_id == 2
).scalar()
print(f"Всего записей в order_product: {total_records}")

db.close()
