"""add the sequence that numbers QuickBooks invoices created from POs

The next number can be changed later with:
    ALTER SEQUENCE qbo_invoice_number_seq RESTART WITH <n>;

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-23

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS qbo_invoice_number_seq START WITH 1000;")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS qbo_invoice_number_seq;")
