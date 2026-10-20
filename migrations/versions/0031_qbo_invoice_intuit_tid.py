"""keep QuickBooks' intuit_tid for each invoice attempt

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The intuit_tid response header identifies a call to Intuit's support.
    op.execute("ALTER TABLE qbo_invoices ADD COLUMN IF NOT EXISTS intuit_tid VARCHAR(64);")


def downgrade() -> None:
    op.execute("ALTER TABLE qbo_invoices DROP COLUMN IF EXISTS intuit_tid;")
