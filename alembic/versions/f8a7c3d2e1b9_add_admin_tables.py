"""add admin tables (AdminActionLog, SystemSetting)

Revision ID: f8a7c3d2e1b9
Revises: e7b3990e9533
Create Date: 2026-07-30 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import JSON


# revision identifiers, used by Alembic.
revision: str = 'f8a7c3d2e1b9'
down_revision: Union[str, None] = '4f6a8e2b1c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Таблица аудита действий администратора (Phase 0 плана ADMIN_IMPLEMENTATION_PLAN.md)
    op.create_table('admin_action_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_user_id', sa.Integer(), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('details', JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_admin_action_logs_id'), 'admin_action_logs', ['id'], unique=False)
    op.create_index(op.f('ix_admin_action_logs_admin_user_id'), 'admin_action_logs', ['admin_user_id'], unique=False)
    op.create_index(op.f('ix_admin_action_logs_target_user_id'), 'admin_action_logs', ['target_user_id'], unique=False)
    op.create_index(op.f('ix_admin_action_logs_action_type'), 'admin_action_logs', ['action_type'], unique=False)
    op.create_index(op.f('ix_admin_action_logs_created_at'), 'admin_action_logs', ['created_at'], unique=False)

    # Таблица глобальных настроек платформы (Phase 0)
    op.create_table('system_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('system_settings')
    op.drop_index(op.f('ix_admin_action_logs_created_at'), table_name='admin_action_logs')
    op.drop_index(op.f('ix_admin_action_logs_action_type'), table_name='admin_action_logs')
    op.drop_index(op.f('ix_admin_action_logs_target_user_id'), table_name='admin_action_logs')
    op.drop_index(op.f('ix_admin_action_logs_admin_user_id'), table_name='admin_action_logs')
    op.drop_index(op.f('ix_admin_action_logs_id'), table_name='admin_action_logs')
    op.drop_table('admin_action_logs')