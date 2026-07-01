"""add performance indexes

Revision ID: e7b3990e9533
Revises: 2240ba87c4bf
Create Date: 2026-07-01 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b3990e9533'
down_revision: Union[str, None] = '2240ba87c4bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Используем сырой SQL для обеспечения идемпотентности (CREATE INDEX IF NOT EXISTS)
    # так как индексы могли быть созданы ранее вручную диагностическим скриптом.
    
    # Индексы для таблицы начислений (OzonAccrual)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ozon_accruals_query ON ozon_accruals (user_id, date, sku)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ozon_accruals_type_query ON ozon_accruals (user_id, date, type_id)")
    
    # Индекс для таблицы себестоимостей (ProductCost)
    op.execute("CREATE INDEX IF NOT EXISTS idx_product_costs_lookup ON product_costs (user_id, sku, effective_from DESC)")
    
    # Индекс для OrderProduct (связь с постингами и SKU)
    op.execute("CREATE INDEX IF NOT EXISTS idx_order_products_sku_user ON order_products (user_id, sku)")


def downgrade() -> None:
    op.drop_index('idx_order_products_sku_user', table_name='order_products')
    op.drop_index('idx_product_costs_lookup', table_name='product_costs')
    op.drop_index('idx_ozon_accruals_type_query', table_name='ozon_accruals')
    op.drop_index('idx_ozon_accruals_query', table_name='ozon_accruals')
