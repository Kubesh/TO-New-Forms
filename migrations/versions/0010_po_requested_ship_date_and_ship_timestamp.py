"""add po_headers.requested_ship_date, widen ship_date to timestamp

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE po_headers ADD COLUMN IF NOT EXISTS requested_ship_date DATE;"
    )
    op.execute(
        "ALTER TABLE po_headers ALTER COLUMN ship_date TYPE TIMESTAMP USING ship_date::timestamp;"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE po_headers ALTER COLUMN ship_date TYPE DATE USING ship_date::date;"
    )
    op.execute("ALTER TABLE po_headers DROP COLUMN IF EXISTS requested_ship_date;")
