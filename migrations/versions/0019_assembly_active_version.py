"""add assemblies.active_version_id for a single active version per assembly

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE assemblies
        ADD COLUMN IF NOT EXISTS active_version_id INTEGER
        REFERENCES assembly_versions (assembly_version_id);
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assemblies_active_version_id "
        "ON assemblies (active_version_id);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_assemblies_active_version_id;")
    op.execute("ALTER TABLE assemblies DROP COLUMN IF EXISTS active_version_id;")
