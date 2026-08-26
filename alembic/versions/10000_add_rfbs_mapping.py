"""add rfbs mapping

Revision ID: 10000
Revises: 9999
Create Date: 2026-08-26 22:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '10000'
down_revision = '9999_fbs_v2'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'ozon_delivery_method_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('delivery_method_id', sa.BigInteger(), nullable=False),
        sa.Column('custom_name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'delivery_method_id', name='uq_user_delivery_method')
    )
    op.create_index(op.f('ix_ozon_delivery_method_mappings_user_id'), 'ozon_delivery_method_mappings', ['user_id'], unique=False)
    op.create_foreign_key('fk_delivery_mapping_user', 'ozon_delivery_method_mappings', 'users', ['user_id'], ['id'], ondelete='CASCADE')

def downgrade():
    op.drop_table('ozon_delivery_method_mappings')
