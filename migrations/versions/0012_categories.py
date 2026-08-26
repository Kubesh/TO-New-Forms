"""create categories table

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            category_id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            parent_id INTEGER REFERENCES categories (category_id),
            color VARCHAR(20),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_top_level_name "
        "ON categories (name) WHERE parent_id IS NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_subcategory_name "
        "ON categories (parent_id, name) WHERE parent_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS categories;")
