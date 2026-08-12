"""add customers.phone_number

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS phone_number VARCHAR(25);")


def downgrade() -> None:
    op.execute("ALTER TABLE customers DROP COLUMN IF EXISTS phone_number;")
