"""invoice number on POs

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE po_headers ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(50);")


def downgrade() -> None:
    op.execute("ALTER TABLE po_headers DROP COLUMN IF EXISTS invoice_number;")
