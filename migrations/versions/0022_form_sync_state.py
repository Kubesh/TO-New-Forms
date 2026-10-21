"""add form_sync_state key/value table

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS form_sync_state (
            key VARCHAR(100) PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS form_sync_state;")
