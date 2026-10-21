"""prices on categories (line / form factor), alongside prices on single SKUs

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A price is now for one item (a SKU) or for one category (a line or a form
    # factor - every item under it), never both.
    op.execute("ALTER TABLE item_prices ALTER COLUMN item_id DROP NOT NULL;")
    op.execute(
        "ALTER TABLE item_prices ADD COLUMN IF NOT EXISTS category_id INTEGER "
        "REFERENCES categories (category_id) ON DELETE CASCADE;"
    )
    op.execute("ALTER TABLE item_prices DROP CONSTRAINT IF EXISTS ck_item_prices_one_target;")
    op.execute(
        "ALTER TABLE item_prices ADD CONSTRAINT ck_item_prices_one_target "
        "CHECK ((item_id IS NULL) <> (category_id IS NULL));"
    )
    # One index covers every combination of target and scope (NULLs never
    # collide in a plain UNIQUE, hence the COALESCEs).
    op.execute("DROP INDEX IF EXISTS ux_item_prices_default;")
    op.execute("DROP INDEX IF EXISTS ux_item_prices_type;")
    op.execute("DROP INDEX IF EXISTS ux_item_prices_customer;")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_item_prices_target_scope ON item_prices ("
        "COALESCE(item_id, 0), COALESCE(category_id, 0), "
        "COALESCE(customer_type_id, 0), COALESCE(customer_id, 0));"
    )


def downgrade() -> None:
    op.execute("DELETE FROM item_prices WHERE item_id IS NULL;")
    op.execute("DROP INDEX IF EXISTS ux_item_prices_target_scope;")
    op.execute("ALTER TABLE item_prices DROP CONSTRAINT IF EXISTS ck_item_prices_one_target;")
    op.execute("ALTER TABLE item_prices DROP COLUMN IF EXISTS category_id;")
    op.execute("ALTER TABLE item_prices ALTER COLUMN item_id SET NOT NULL;")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_item_prices_default "
        "ON item_prices (item_id) WHERE customer_type_id IS NULL AND customer_id IS NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_item_prices_type "
        "ON item_prices (item_id, customer_type_id) WHERE customer_type_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_item_prices_customer "
        "ON item_prices (item_id, customer_id) WHERE customer_id IS NOT NULL;"
    )
