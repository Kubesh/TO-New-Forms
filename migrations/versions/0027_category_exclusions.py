"""categories that aren't sold to a customer type / customer

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A row means items in that category (and under it) aren't sold to that
    # customer type or customer (and, for a parent account, its sub-accounts).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS category_exclusions (
            category_exclusion_id SERIAL PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES categories (category_id) ON DELETE CASCADE,
            customer_type_id INTEGER REFERENCES customer_types (customer_type_id) ON DELETE CASCADE,
            customer_id INTEGER REFERENCES customers (customer_id) ON DELETE CASCADE,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT ck_category_exclusions_one_scope
                CHECK ((customer_type_id IS NULL) <> (customer_id IS NULL))
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_category_exclusions_scope ON category_exclusions "
        "(category_id, COALESCE(customer_type_id, 0), COALESCE(customer_id, 0));"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS category_exclusions;")
