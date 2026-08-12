"""rename po_headers.account_type to order_type

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'po_headers' AND column_name = 'account_type'
            ) THEN
                ALTER TABLE po_headers RENAME COLUMN account_type TO order_type;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'po_headers' AND column_name = 'order_type'
            ) THEN
                ALTER TABLE po_headers RENAME COLUMN order_type TO account_type;
            END IF;
        END $$;
        """
    )
