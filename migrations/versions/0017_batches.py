"""create batches and batch_items

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS batches (
            batch_id SERIAL PRIMARY KEY,
            version_id INTEGER NOT NULL REFERENCES assembly_versions (assembly_version_id),
            parent_id INTEGER REFERENCES batches (batch_id),
            batch_code VARCHAR(100) NOT NULL,
            expire_date DATE,
            released_at TIMESTAMP,
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_items (
            batch_item_id SERIAL PRIMARY KEY,
            batch_id INTEGER NOT NULL REFERENCES batches (batch_id),
            product_id INTEGER NOT NULL REFERENCES items (item_id),
            units DOUBLE PRECISION NOT NULL,
            lot_number VARCHAR(100),
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_batches_version_id ON batches (version_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batches_parent_id ON batches (parent_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_items_batch_id ON batch_items (batch_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_items_product_id ON batch_items (product_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS batch_items;")
    op.execute("DROP TABLE IF EXISTS batches;")
