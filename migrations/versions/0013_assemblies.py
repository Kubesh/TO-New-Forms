"""create assemblies and assembly_items

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assemblies (
            assembly_id SERIAL PRIMARY KEY,
            assembly_name VARCHAR(255) NOT NULL,
            version_name VARCHAR(100),
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assembly_items (
            assembly_item_id SERIAL PRIMARY KEY,
            assembly_id INTEGER NOT NULL REFERENCES assemblies (assembly_id),
            product_id INTEGER NOT NULL REFERENCES items (item_id),
            amount INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assembly_items_assembly_id "
        "ON assembly_items (assembly_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assembly_items_product_id "
        "ON assembly_items (product_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assembly_items;")
    op.execute("DROP TABLE IF EXISTS assemblies;")
