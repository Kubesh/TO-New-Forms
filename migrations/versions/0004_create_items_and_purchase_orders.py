"""create items, po_headers, po_line_items

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            item_id SERIAL PRIMARY KEY,
            sku VARCHAR(50) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            category VARCHAR(100),
            subcategory VARCHAR(100),
            search_terms TEXT,
            measured_in VARCHAR(50),
            unit_weight_lb NUMERIC(10, 4),
            sellable_content_weight_lb NUMERIC(10, 4),
            shopify_item_number VARCHAR(50),
            shopify_variant_number VARCHAR(50),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS po_headers (
            po_id SERIAL PRIMARY KEY,
            po_number VARCHAR(50) NOT NULL UNIQUE,
            customer_id INTEGER REFERENCES customers (customer_id),
            store_key INTEGER,
            account_type VARCHAR(50),
            order_date DATE,
            due_date DATE,
            ship_date DATE,
            order_entry_timestamp TIMESTAMP,
            note TEXT,
            voided BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_po_headers_customer_id ON po_headers (customer_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_po_headers_store_key ON po_headers (store_key);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS po_line_items (
            line_item_id SERIAL PRIMARY KEY,
            po_id INTEGER NOT NULL REFERENCES po_headers (po_id),
            item_id INTEGER REFERENCES items (item_id),
            sku VARCHAR(50),
            item_description TEXT,
            quantity NUMERIC(12, 4) NOT NULL,
            expanded_weight NUMERIC(12, 4),
            box VARCHAR(50),
            shopify_item_number VARCHAR(50),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_po_line_items_po_id ON po_line_items (po_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_po_line_items_item_id ON po_line_items (item_id);")

    for table in ("items", "po_headers", "po_line_items"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON {table};")
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_set_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in ("po_line_items", "po_headers", "items"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON {table};")

    op.execute("DROP TABLE IF EXISTS po_line_items;")
    op.execute("DROP TABLE IF EXISTS po_headers;")
    op.execute("DROP TABLE IF EXISTS items;")
