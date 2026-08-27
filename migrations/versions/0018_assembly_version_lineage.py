"""add assembly_versions.replaces_version_id for tracking version lineage

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE assembly_versions
        ADD COLUMN IF NOT EXISTS replaces_version_id INTEGER
        REFERENCES assembly_versions (assembly_version_id);
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assembly_versions_replaces_version_id "
        "ON assembly_versions (replaces_version_id);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_assembly_versions_replaces_version_id;")
    op.execute("ALTER TABLE assembly_versions DROP COLUMN IF EXISTS replaces_version_id;")
