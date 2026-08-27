"""widen inventory_count_items.counted to a decimal

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The historical count-import data has fractional counts (weight-based
    # items counted in lbs, e.g. 61.80342906) - widen rather than round so
    # importing it doesn't lose precision.
    op.execute("ALTER TABLE inventory_count_items ALTER COLUMN counted TYPE NUMERIC(14, 8);")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE inventory_count_items ALTER COLUMN counted TYPE INTEGER "
        "USING round(counted)::INTEGER;"
    )
