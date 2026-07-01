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
    # Индексы для таблицы начислений (OzonAccrual)
    op.create_index('idx_ozon_accruals_query', 'ozon_accruals', ['user_id', 'date', 'sku'], unique=False)
    op.create_index('idx_ozon_accruals_type_query', 'ozon_accruals', ['user_id', 'date', 'type_id'], unique=False)
    
    # Индекс для таблицы себестоимостей (ProductCost)
    # Удаляем старый если есть и создаем правильный
    op.create_index('idx_product_costs_lookup', 'product_costs', ['user_id', 'sku', sa.text('effective_from DESC')], unique=False)
    
    # Индекс для OrderProduct (связь с постингами и SKU)
    op.create_index('idx_order_products_sku_user', 'order_products', ['user_id', 'sku'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_order_products_sku_user', table_name='order_products')
    op.drop_index('idx_product_costs_lookup', table_name='product_costs')
    op.drop_index('idx_ozon_accruals_type_query', table_name='ozon_accruals')
    op.drop_index('idx_ozon_accruals_query', table_name='ozon_accruals')
