"""add po_line_items.original_quantity

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE po_line_items ADD COLUMN IF NOT EXISTS original_quantity NUMERIC(12, 4);"
    )
    # Backfill: for rows that predate this column, the quantity on file is by
    # definition what was originally entered (nothing has edited it yet).
    op.execute(
        "UPDATE po_line_items SET original_quantity = quantity WHERE original_quantity IS NULL;"
    )
    op.execute("ALTER TABLE po_line_items ALTER COLUMN original_quantity SET NOT NULL;")


def downgrade() -> None:
    op.execute("ALTER TABLE po_line_items DROP COLUMN IF EXISTS original_quantity;")
