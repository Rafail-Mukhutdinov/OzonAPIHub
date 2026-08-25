"""add fbs support fields v2

Revision ID: 9999_fbs_v2
Revises: f8a7c3d2e1b9
Create Date: 2026-08-25 16:10:00

"""
from alembic import op
import sqlalchemy as sa

revision = '9999_fbs_v2'
down_revision = 'f8a7c3d2e1b9'
branch_labels = None
depends_on = None

def upgrade():
    # 1. Добавляем колонки в orders
    op.add_column('orders', sa.Column('scheme', sa.String(length=20), server_default='fbo', nullable=True))
    op.create_index('idx_order_scheme_user', 'orders', ['scheme', 'user_id', 'created_at'])

    # 2. Добавляем колонки в order_postings
    op.add_column('order_postings', sa.Column('scheme', sa.String(length=20), server_default='fbo', nullable=True))
    op.add_column('order_postings', sa.Column('is_express', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('order_postings', sa.Column('shipment_date', sa.DateTime(), nullable=True))
    op.add_column('order_postings', sa.Column('tpl_provider', sa.String(length=255), nullable=True))
    op.add_column('order_postings', sa.Column('delivery_method_id', sa.BigInteger(), nullable=True))
    op.add_column('order_postings', sa.Column('delivery_method_name', sa.String(length=255), nullable=True))
    op.add_column('order_postings', sa.Column('tracking_number', sa.String(length=255), nullable=True))
    op.create_index('idx_posting_scheme_user', 'order_postings', ['scheme', 'user_id', 'created_at'])
    op.create_index('ix_order_postings_shipment_date', 'order_postings', ['shipment_date'], unique=False)

    # 3. Добавляем scheme в ozon_accruals
    op.add_column('ozon_accruals', sa.Column('scheme', sa.String(length=20), server_default='fbo', nullable=True))
    op.create_index('ix_ozon_accruals_scheme', 'ozon_accruals', ['scheme'])

    # 4. Добавляем поля в sync_status
    op.add_column('sync_status', sa.Column('fbs_last_sync_at', sa.DateTime(), nullable=True))
    op.add_column('sync_status', sa.Column('fbs_backfill_cursor', sa.DateTime(), nullable=True))
    op.add_column('sync_status', sa.Column('fbs_backfill_is_complete', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('sync_status', sa.Column('accruals_backfill_cursor', sa.DateTime(), nullable=True))

    # 5. Бэкфилл данных
    op.execute("UPDATE orders SET scheme = 'fbo' WHERE scheme IS NULL")
    op.execute("UPDATE order_postings SET scheme = 'fbo' WHERE scheme IS NULL")
    op.execute("UPDATE ozon_accruals SET scheme = 'fbo' WHERE scheme IS NULL")

def downgrade():
    op.drop_index('ix_ozon_accruals_scheme', table_name='ozon_accruals')
    op.drop_index('ix_order_postings_shipment_date', table_name='order_postings')
    op.drop_index('idx_posting_scheme_user', table_name='order_postings')
    op.drop_index('idx_order_scheme_user', table_name='orders')
    op.drop_column('sync_status', 'accruals_backfill_cursor')
    op.drop_column('sync_status', 'fbs_backfill_is_complete')
    op.drop_column('sync_status', 'fbs_backfill_cursor')
    op.drop_column('sync_status', 'fbs_last_sync_at')
    op.drop_column('ozon_accruals', 'scheme')
    op.drop_column('order_postings', 'tracking_number')
    op.drop_column('order_postings', 'delivery_method_name')
    op.drop_column('order_postings', 'delivery_method_id')
    op.drop_column('order_postings', 'tpl_provider')
    op.drop_column('order_postings', 'shipment_date')
    op.drop_column('order_postings', 'is_express')
    op.drop_column('order_postings', 'scheme')
    op.drop_column('orders', 'scheme')
