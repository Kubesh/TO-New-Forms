"""add customers.store_key and customers.notes

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS store_key INTEGER;")
    op.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS notes VARCHAR(100);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_customers_store_key ON customers (store_key);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_customers_store_key;")
    op.execute("ALTER TABLE customers DROP COLUMN IF EXISTS notes;")
    op.execute("ALTER TABLE customers DROP COLUMN IF EXISTS store_key;")
