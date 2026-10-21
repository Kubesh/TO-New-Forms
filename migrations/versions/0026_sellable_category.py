"""Sellable Product category, and form factors only under it

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pricing and form factors hang off this top-level category, so it has to exist.
    op.execute(
        """
        INSERT INTO categories (name, parent_id, color, created_at, updated_at)
        SELECT 'Sellable Product', NULL, NULL, now(), now()
        WHERE NOT EXISTS (
            SELECT 1 FROM categories WHERE name = 'Sellable Product' AND parent_id IS NULL
        );
        """
    )
    # Form factors (a third level) are only for Sellable Product. Move any
    # items in one elsewhere up onto its parent, then remove it.
    op.execute(
        """
        UPDATE items SET category_id = c.parent_id
        FROM categories c
        JOIN categories p ON p.category_id = c.parent_id
        JOIN categories g ON g.category_id = p.parent_id
        WHERE items.category_id = c.category_id
          AND g.parent_id IS NULL AND g.name <> 'Sellable Product';
        """
    )
    op.execute(
        """
        DELETE FROM categories c
        USING categories p, categories g
        WHERE c.parent_id = p.category_id AND p.parent_id = g.category_id
          AND g.parent_id IS NULL AND g.name <> 'Sellable Product';
        """
    )


def downgrade() -> None:
    pass
