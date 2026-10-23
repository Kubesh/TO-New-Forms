"""add help_pages: per-page help text (markdown) edited in the app

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-23

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS help_pages (
            page_key VARCHAR(100) PRIMARY KEY,
            content TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS help_pages;")
