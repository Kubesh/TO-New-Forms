"""widen assembly_version_items.amount to a decimal

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recipe amounts (e.g. 26.20 parts per batch) aren't whole numbers -
    # this table only just landed (0015) and isn't in real use yet, so
    # there's no existing data to convert.
    op.execute("ALTER TABLE assembly_version_items ALTER COLUMN amount TYPE NUMERIC(12, 4);")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE assembly_version_items ALTER COLUMN amount TYPE INTEGER "
        "USING round(amount)::INTEGER;"
    )
