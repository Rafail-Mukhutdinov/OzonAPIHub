#!/usr/bin/env python3
"""
Скрипт для очистки базы данных от дубликатов в таблице 'order_products'.

Назначение:
    - Исправляет ошибки дублирования товаров в одном заказе, которые могли возникнуть 
      при повторной синхронизации или сбоях в транзакциях.
    - Важен для корректного расчета общей суммы продаж и количества проданных единиц.

Логика работы:
    1. Идентифицирует "уникальную" запись как комбинацию (posting_number, offer_id, sku).
    2. Использует подзапрос для поиска минимального ID для каждой такой комбинации (это запись, которую мы оставим).
    3. Находит все записи, ID которых не входят в список минимальных, и помечает их как дубликаты.
    4. Массово удаляет дубликаты и выводит итоговую статистику по количеству товаров.

Ключевые переменные:
    - min_id_subquery: SQL подзапрос, группирующий товары и возвращающий ID первого вхождения.
    - duplicates_to_delete: Список ID лишних записей.
    - total_qty: Суммарное количество товаров после очистки (для проверки).
"""
import sys
# Добавление пути для работы в Docker или локально
sys.path.insert(0, '/workspace')

from db.database import SessionLocal, OrderProduct
from sqlalchemy import func

db = SessionLocal()

print("=== Поиск и удаление дубликатов в товарах ===")

# Логика дедупликации:
# Мы группируем записи по ключевым полям товара в рамках заказа и пользователя.
# Оставляем только ту запись, которая была создана первой (с наименьшим ID).

from sqlalchemy.orm import aliased

# Шаг 1: Подзапрос для поиска "эталонных" ID
min_id_subquery = db.query(
    func.min(OrderProduct.id).label("min_id")
).group_by(
    OrderProduct.posting_number,
    OrderProduct.offer_id,
    OrderProduct.sku,
    OrderProduct.user_id
).subquery()

# Шаг 2: Выборка всех записей, которые НЕ являются эталонными
duplicates_to_delete = db.query(OrderProduct.id).filter(
    ~OrderProduct.id.in_(
        db.query(min_id_subquery.c.min_id).select_from(min_id_subquery)
    )
).all()

print(f"Найдено дублей для удаления: {len(duplicates_to_delete)}")

if duplicates_to_delete:
    # Извлечение чистых ID из результатов запроса
    ids_to_delete = [row[0] for row in duplicates_to_delete]
    
    # Шаг 3: Массовое удаление дублей
    deleted_count = db.query(OrderProduct).filter(OrderProduct.id.in_(ids_to_delete)).delete(synchronize_session=False)
    db.commit()
    
    print(f"Успешно удалено записей: {deleted_count}")
    
    # Пересчет и вывод итоговых показателей для контроля целостности
    print("\n=== Статистика после очистки ===")
    total_qty = db.query(func.sum(OrderProduct.quantity)).scalar() or 0
    total_records = db.query(func.count(OrderProduct.id)).scalar() or 0
    total_postings = db.query(func.count(func.distinct(OrderProduct.posting_number))).scalar() or 0
    
    print(f"Общее кол-во товаров (сумма qty): {total_qty}")
    print(f"Количество записей в таблице: {total_records}")
    print(f"Уникальных заказов с товарами: {total_postings}")
else:
    print("Дубликатов не обнаружено.")

db.close()
