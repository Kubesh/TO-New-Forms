"""add items.sellable/shipping_material, integer po line item quantities, order_shipping_materials

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS sellable BOOLEAN NOT NULL DEFAULT true;"
    )
    op.execute(
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS shipping_material BOOLEAN NOT NULL "
        "DEFAULT false;"
    )

    op.execute(
        "ALTER TABLE po_line_items ALTER COLUMN quantity TYPE INTEGER "
        "USING ROUND(quantity)::INTEGER;"
    )
    op.execute(
        "ALTER TABLE po_line_items ALTER COLUMN original_quantity TYPE INTEGER "
        "USING ROUND(original_quantity)::INTEGER;"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS order_shipping_materials (
            order_shipping_material_id SERIAL PRIMARY KEY,
            po_id INTEGER NOT NULL REFERENCES po_headers (po_id),
            item_id INTEGER NOT NULL REFERENCES items (item_id),
            quantity INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_shipping_materials_po_id "
        "ON order_shipping_materials (po_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_shipping_materials_item_id "
        "ON order_shipping_materials (item_id);"
    )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_order_shipping_materials_set_updated_at "
        "ON order_shipping_materials;"
    )
    op.execute(
        """
        CREATE TRIGGER trg_order_shipping_materials_set_updated_at
        BEFORE UPDATE ON order_shipping_materials
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_order_shipping_materials_set_updated_at "
        "ON order_shipping_materials;"
    )
    op.execute("DROP TABLE IF EXISTS order_shipping_materials;")
    op.execute("ALTER TABLE po_line_items ALTER COLUMN original_quantity TYPE NUMERIC(12, 4);")
    op.execute("ALTER TABLE po_line_items ALTER COLUMN quantity TYPE NUMERIC(12, 4);")
    op.execute("ALTER TABLE items DROP COLUMN IF EXISTS shipping_material;")
    op.execute("ALTER TABLE items DROP COLUMN IF EXISTS sellable;")
