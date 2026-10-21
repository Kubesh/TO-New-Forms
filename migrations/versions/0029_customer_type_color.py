"""customer type color

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE customer_types ADD COLUMN IF NOT EXISTS color VARCHAR(20);")


def downgrade() -> None:
    op.execute("ALTER TABLE customer_types DROP COLUMN IF EXISTS color;")
