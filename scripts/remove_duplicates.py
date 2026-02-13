#!/usr/bin/env python3
"""
Скрипт для удаления дублей в order_product.
Сохраняет первую запись каждого (posting_number, offer_id, sku) и удаляет остальные.
"""
import sys
sys.path.insert(0, '/workspace')

from db.database import SessionLocal, OrderProduct
from sqlalchemy import func

db = SessionLocal()

print("=== Поиск дублей ===")

# Найти дубли: группировать по (posting_number, offer_id, sku) и оставить только min(id)
from sqlalchemy.orm import aliased

# Подзапрос: для каждого (posting_number, offer_id, sku, user_id) найди MIN(id)
min_id_subquery = db.query(
    func.min(OrderProduct.id).label("min_id")
).group_by(
    OrderProduct.posting_number,
    OrderProduct.offer_id,
    OrderProduct.sku,
    OrderProduct.user_id
).subquery()

# Теперь найди все записи которые НЕ являются min_id  для своей группы
duplicates_to_delete = db.query(OrderProduct.id).filter(
    ~OrderProduct.id.in_(
        db.query(min_id_subquery.c.min_id).select_from(min_id_subquery)
    )
).all()

print(f"Найдено дублей для удаления: {len(duplicates_to_delete)}")

if duplicates_to_delete:
    ids_to_delete = [row[0] for row in duplicates_to_delete]
    
    # Удаляем дубли
    deleted_count = db.query(OrderProduct).filter(OrderProduct.id.in_(ids_to_delete)).delete(synchronize_session=False)
    db.commit()
    
    print(f"Удалено дублей: {deleted_count}")
    
    # Пересчитаем totals
    print("\n=== Новые totals ===")
    total_qty = db.query(func.sum(OrderProduct.quantity)).scalar() or 0
    total_records = db.query(func.count(OrderProduct.id)).scalar() or 0
    total_postings = db.query(func.count(func.distinct(OrderProduct.posting_number))).scalar() or 0
    
    print(f"Всего товаров (qty sum): {total_qty}")
    print(f"Всего записей: {total_records}")
    print(f"Уникальных постингов: {total_postings}")
else:
    print("Дублей не найдено")

db.close()
