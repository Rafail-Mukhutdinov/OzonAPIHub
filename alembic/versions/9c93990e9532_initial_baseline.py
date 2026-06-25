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
    # Оставляем пустой, так как таблицы создаются через Base.metadata.create_all в коде сервера
    pass

def downgrade() -> None:
    pass
