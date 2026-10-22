"""add customers.bill_to_email and customers.ship_to_email

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-22

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS bill_to_email VARCHAR(255);")
    op.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS ship_to_email VARCHAR(255);")


def downgrade() -> None:
    op.execute("ALTER TABLE customers DROP COLUMN IF EXISTS ship_to_email;")
    op.execute("ALTER TABLE customers DROP COLUMN IF EXISTS bill_to_email;")
