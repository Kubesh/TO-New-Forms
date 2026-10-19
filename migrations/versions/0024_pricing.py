"""pricing: item_prices, and a price snapshot on PO line items

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Per-case starting prices (the rest are entered on the Pricing page later).
STANDARD_DRINKING_CHOCOLATE = ("01010110", "01020110", "01030110", "01040110", "01050110")
SUP_DRINKING_CHOCOLATE_AND_CREAMERS = (
    "01010205",
    "01050205",
    "02010205",
    "02020205",
    "02030205",
    "02040205",
)


def upgrade() -> None:
    # One row per price. Scope is one of: a customer (that customer's own
    # price), a customer type (the price for every customer of that type), or
    # neither (the default, used when nothing more specific is set).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS item_prices (
            item_price_id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items (item_id) ON DELETE CASCADE,
            customer_type_id INTEGER REFERENCES customer_types (customer_type_id) ON DELETE CASCADE,
            customer_id INTEGER REFERENCES customers (customer_id) ON DELETE CASCADE,
            price NUMERIC(12, 4) NOT NULL CHECK (price >= 0),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT ck_item_prices_one_scope
                CHECK (customer_type_id IS NULL OR customer_id IS NULL)
        );
        """
    )
    # NULLs never collide in a plain UNIQUE, so each scope gets its own index.
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

    # The price a line was entered at, kept on the line so later price changes
    # don't rewrite old POs. NULL on lines entered before pricing existed.
    op.execute("ALTER TABLE po_line_items ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12, 4);")
    op.execute("ALTER TABLE po_line_items ADD COLUMN IF NOT EXISTS price_source VARCHAR(20);")

    standard = ", ".join(f"'{sku}'" for sku in STANDARD_DRINKING_CHOCOLATE)
    sup = ", ".join(f"'{sku}'" for sku in SUP_DRINKING_CHOCOLATE_AND_CREAMERS)
    op.execute(
        f"""
        INSERT INTO item_prices (item_id, price)
        SELECT item_id, 17.50 FROM items WHERE sku IN ({standard})
        ON CONFLICT DO NOTHING;
        """
    )
    op.execute(
        f"""
        INSERT INTO item_prices (item_id, price)
        SELECT item_id, 35.95 FROM items WHERE sku IN ({sup})
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE po_line_items DROP COLUMN IF EXISTS price_source;")
    op.execute("ALTER TABLE po_line_items DROP COLUMN IF EXISTS unit_price;")
    op.execute("DROP TABLE IF EXISTS item_prices;")
