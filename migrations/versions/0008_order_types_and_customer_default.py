"""add order_types table and customers.default_order_type_id

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED_ORDER_TYPES = ["Direct", "Faire Order", "Distributor"]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS order_types (
            order_type_id SERIAL PRIMARY KEY,
            name VARCHAR(50) NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_order_types_set_updated_at ON order_types;"
    )
    op.execute(
        """
        CREATE TRIGGER trg_order_types_set_updated_at
        BEFORE UPDATE ON order_types
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )

    for name in SEED_ORDER_TYPES:
        op.execute(f"INSERT INTO order_types (name) VALUES ('{name}') ON CONFLICT (name) DO NOTHING;")

    op.execute(
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS default_order_type_id INTEGER "
        "REFERENCES order_types (order_type_id);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE customers DROP COLUMN IF EXISTS default_order_type_id;")
    op.execute("DROP TRIGGER IF EXISTS trg_order_types_set_updated_at ON order_types;")
    op.execute("DROP TABLE IF EXISTS order_types;")
