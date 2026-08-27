"""backfill assemblies.active_version_id: single-version assemblies, and
any assembly with a version named 'Current'

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # An assembly with exactly one version - that's the active one.
    op.execute(
        """
        UPDATE assemblies a
        SET active_version_id = sub.assembly_version_id
        FROM (
            SELECT assembly_id, MIN(assembly_version_id) AS assembly_version_id
            FROM assembly_versions
            GROUP BY assembly_id
            HAVING COUNT(*) = 1
        ) sub
        WHERE a.assembly_id = sub.assembly_id;
        """
    )
    # Any assembly with a version literally named "Current" - that one wins
    # regardless of how many versions the assembly has.
    op.execute(
        """
        UPDATE assemblies a
        SET active_version_id = v.assembly_version_id
        FROM assembly_versions v
        WHERE v.assembly_id = a.assembly_id
          AND v.version_name = 'Current';
        """
    )


def downgrade() -> None:
    op.execute("UPDATE assemblies SET active_version_id = NULL;")
