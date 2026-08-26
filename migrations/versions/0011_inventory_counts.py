"""create inventory_counts and inventory_count_items

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_counts (
            inventory_count_id SERIAL PRIMARY KEY,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_count_items (
            inventory_count_item_id SERIAL PRIMARY KEY,
            inventory_count_id INTEGER NOT NULL
                REFERENCES inventory_counts (inventory_count_id),
            item_id INTEGER NOT NULL REFERENCES items (item_id),
            counted INTEGER NOT NULL,
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_inventory_count_items_item_id "
        "ON inventory_count_items (item_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inventory_count_items;")
    op.execute("DROP TABLE IF EXISTS inventory_counts;")
