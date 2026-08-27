"""replace items.category/subcategory strings with items.category_id

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS category_id INTEGER "
        "REFERENCES categories (category_id);"
    )

    # Promote every distinct category/subcategory string already in use on
    # items into a real categories row, so no item's classification is lost
    # just because nobody had gone to the Categories page and created it
    # there yet.
    op.execute(
        """
        INSERT INTO categories (name, parent_id, color, created_at, updated_at)
        SELECT DISTINCT i.category, NULL::INTEGER, NULL::VARCHAR(20), now(), now()
        FROM items i
        WHERE i.category IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM categories c
              WHERE c.name = i.category AND c.parent_id IS NULL
          );
        """
    )
    op.execute(
        """
        INSERT INTO categories (name, parent_id, color, created_at, updated_at)
        SELECT DISTINCT i.subcategory, c.category_id, NULL::VARCHAR(20), now(), now()
        FROM items i
        JOIN categories c ON c.name = i.category AND c.parent_id IS NULL
        WHERE i.subcategory IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM categories sc
              WHERE sc.name = i.subcategory AND sc.parent_id = c.category_id
          );
        """
    )

    # Point each item at the most specific matching row - its subcategory's
    # row if it had one, otherwise its top-level category's row.
    op.execute(
        """
        UPDATE items i
        SET category_id = COALESCE(
            (SELECT sc.category_id FROM categories sc
               JOIN categories c ON sc.parent_id = c.category_id
              WHERE c.name = i.category AND sc.name = i.subcategory),
            (SELECT c.category_id FROM categories c
              WHERE c.name = i.category AND c.parent_id IS NULL)
        );
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_items_category_id ON items (category_id);")
    op.execute("ALTER TABLE items DROP COLUMN IF EXISTS category;")
    op.execute("ALTER TABLE items DROP COLUMN IF EXISTS subcategory;")


def downgrade() -> None:
    op.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS category VARCHAR(100);")
    op.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS subcategory VARCHAR(100);")
    op.execute(
        """
        UPDATE items i
        SET category = COALESCE(parent_c.name, c.name),
            subcategory = CASE WHEN c.parent_id IS NOT NULL THEN c.name ELSE NULL END
        FROM categories c
        LEFT JOIN categories parent_c ON parent_c.category_id = c.parent_id
        WHERE i.category_id = c.category_id;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_items_category_id;")
    op.execute("ALTER TABLE items DROP COLUMN IF EXISTS category_id;")
