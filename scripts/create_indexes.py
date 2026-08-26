"""
Скрипт для оптимизации базы данных путем создания дополнительных индексов.

Назначение:
    - Повышает скорость формирования финансовых отчетов.
    - Оптимизирует поиск по таблицам с большим объемом данных (начисления и себестоимость).

Создаваемые индексы:
    - idx_ozon_accruals_query: Ускоряет выборку начислений за конкретные даты по конкретным товарам (SKU).
    - idx_product_costs_lookup: Обеспечивает мгновенный поиск актуальной себестоимости товара на дату.
    - idx_order_products_sku: Ускоряет фильтрацию товаров в заказах.
"""
import os
import sys
from sqlalchemy import text

# Настройка путей
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import engine

def create_indexes():
    """
    Выполняет SQL-команды создания индексов.
    Используется 'IF NOT EXISTS', чтобы избежать ошибок при повторном запуске.
    """
    print("Создание индексов для ускорения аналитики...")
    with engine.connect() as conn:
        # Индексы для таблицы начислений (OzonAccrual)
        # Важен для отчета P&L и Unit-экономики
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ozon_accruals_query ON ozon_accruals (user_id, date, sku)"))
        
        # Индекс для таблицы себестоимостей (ProductCost)
        # Используется для подгрузки цен закупки с учетом даты вступления в силу (effective_from)
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_product_costs_lookup ON product_costs (user_id, sku, effective_from DESC)"))
        
        # Индекс для OrderProduct (связь с постингами и SKU)
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_products_sku ON order_products (sku, user_id)"))
        
        conn.commit()
    print("Индексы успешно созданы.")

if __name__ == "__main__":
    create_indexes()
