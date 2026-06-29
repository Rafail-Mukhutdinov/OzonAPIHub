"""Initial baseline

Revision ID: 9c93990e9532
Revises: None
Create Date: 2026-06-23 14:25:07.543883

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9c93990e9532'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('subscription_end_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    # ozon_credentials
    op.create_table(
        'ozon_credentials',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('marketplace', sa.String(50), nullable=False, server_default='ozon'),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('client_id_encrypted', sa.Text(), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'name', name='uq_user_credential_name'),
    )

    # orders
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('order_id', sa.BigInteger(), index=True),
        sa.Column('posting_number', sa.String(255), index=True),
        sa.Column('status', sa.String(100)),
        sa.Column('created_at', sa.DateTime(), index=True),
        sa.Column('updated_at', sa.DateTime(), index=True),
        sa.Column('data', sa.JSON()),
        sa.UniqueConstraint('user_id', 'posting_number', name='uq_user_posting'),
    )
    op.create_index('idx_order_user_created', 'orders', ['user_id', 'created_at'])

    # order_headers
    op.create_table(
        'order_headers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('order_number', sa.String(255), index=True),
        sa.Column('first_created_at', sa.DateTime()),
        sa.Column('last_delivery_at', sa.DateTime()),
        sa.Column('total_payout', sa.Integer()),
        sa.Column('total_commission', sa.Integer()),
        sa.UniqueConstraint('user_id', 'order_number', name='uq_user_order_number'),
    )

    # order_postings
    op.create_table(
        'order_postings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('order_number', sa.String(255), index=True),
        sa.Column('posting_number', sa.String(255), index=True),
        sa.Column('status', sa.String(100)),
        sa.Column('created_at', sa.DateTime(), index=True),
        sa.Column('in_process_at', sa.DateTime(), index=True),
        sa.Column('fact_delivery_date', sa.DateTime()),
        sa.Column('substatus', sa.String(100)),
        sa.Column('analytics_data', sa.JSON()),
        sa.Column('financial_data', sa.JSON()),
        sa.UniqueConstraint('user_id', 'posting_number', name='uq_user_posting_number'),
    )
    op.create_index('idx_posting_user_created', 'order_postings', ['user_id', 'created_at'])
    op.create_index('idx_posting_user_in_process', 'order_postings', ['user_id', 'in_process_at'])

    # order_products
    op.create_table(
        'order_products',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('posting_id', sa.Integer(), sa.ForeignKey('order_postings.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('posting_number', sa.String(255), index=True),
        sa.Column('sku', sa.BigInteger(), index=True),
        sa.Column('offer_id', sa.String(255), index=True),
        sa.Column('name', sa.String(500)),
        sa.Column('quantity', sa.Integer()),
        sa.Column('price', sa.Integer()),
        sa.Column('currency_code', sa.String(10)),
        sa.Column('commission_amount', sa.Integer()),
        sa.Column('commission_percent', sa.Integer()),
        sa.Column('payout', sa.Integer()),
        sa.Column('total_discount_value', sa.Integer()),
        sa.Column('total_discount_percent', sa.Integer()),
        sa.Column('image_url', sa.String(1024), nullable=True),
    )

    # costs
    op.create_table(
        'costs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('type', sa.String(50), index=True),
        sa.Column('amount', sa.Integer()),
        sa.Column('currency', sa.String(10), server_default='RUB'),
        sa.Column('date', sa.DateTime(), index=True),
        sa.Column('scope_order_number', sa.String(255), index=True, nullable=True),
        sa.Column('scope_posting_number', sa.String(255), index=True, nullable=True),
        sa.Column('scope_sku', sa.BigInteger(), index=True, nullable=True),
        sa.Column('scope_offer_id', sa.String(255), index=True, nullable=True),
        sa.Column('notes', sa.Text()),
    )

    # ozon_accruals
    op.create_table(
        'ozon_accruals',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ozon_accrual_id', sa.BigInteger(), index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('date', sa.DateTime(), index=True, nullable=False),
        sa.Column('unit_number', sa.String(255), index=True),
        sa.Column('accrued_category', sa.String(50), index=True),
        sa.Column('operation_type', sa.String(20), index=True, server_default='expense'),
        sa.Column('amount', sa.Float()),
        sa.Column('currency', sa.String(10)),
        sa.Column('type_id', sa.Integer(), index=True),
        sa.Column('sku', sa.BigInteger(), index=True),
        sa.Column('posting_id', sa.Integer(), sa.ForeignKey('order_postings.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime()),
    )

    # sync_status
    op.create_table(
        'sync_status',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True, unique=True),
        sa.Column('is_syncing', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('status_message', sa.String(255), nullable=False, server_default=''),
        sa.Column('sync_started_at', sa.DateTime(), nullable=True),
        sa.Column('sync_completed_at', sa.DateTime(), nullable=True),
        sa.Column('total_records_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('backfill_cursor', sa.DateTime(), nullable=True),
        sa.Column('backfill_started_at', sa.DateTime(), nullable=True),
        sa.Column('backfill_completed_at', sa.DateTime(), nullable=True),
        sa.Column('backfill_from', sa.DateTime(), nullable=True),
        sa.Column('backfill_to', sa.DateTime(), nullable=True),
        sa.Column('backfill_is_complete', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_table('sync_status')
    op.drop_table('ozon_accruals')
    op.drop_table('costs')
    op.drop_table('order_products')
    op.drop_index('idx_posting_user_in_process', table_name='order_postings')
    op.drop_index('idx_posting_user_created', table_name='order_postings')
    op.drop_table('order_postings')
    op.drop_table('order_headers')
    op.drop_index('idx_order_user_created', table_name='orders')
    op.drop_table('orders')
    op.drop_table('ozon_credentials')
    op.drop_table('users')