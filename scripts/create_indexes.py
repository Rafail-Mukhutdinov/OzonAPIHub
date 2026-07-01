import os
import sys
from sqlalchemy import text

# Setup path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import engine

def create_indexes():
    print("Создание индексов для ускорения аналитики...")
    with engine.connect() as conn:
        # Индексы для таблицы начислений (OzonAccrual)
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ozon_accruals_query ON ozon_accruals (user_id, date, sku)"))
        
        # Индекс для таблицы себестоимостей (ProductCost)
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_product_costs_lookup ON product_costs (user_id, sku, effective_from DESC)"))
        
        # Индекс для OrderProduct (связь с постингами)
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_products_sku ON order_products (sku, user_id)"))
        
        conn.commit()
    print("Индексы успешно созданы.")

if __name__ == "__main__":
    create_indexes()
