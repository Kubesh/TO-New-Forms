"""restructure assemblies into assemblies/assembly_versions/assembly_version_items

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This feature (0013) only just landed and isn't in real use yet, so
    # this replaces its two tables outright rather than migrating data -
    # a version_name is now a whole AssemblyVersion row, not a column on
    # Assembly, so there's no like-for-like column to preserve anyway.
    op.execute("DROP TABLE IF EXISTS assembly_items;")
    op.execute("DROP TABLE IF EXISTS assemblies;")

    op.execute(
        """
        CREATE TABLE assemblies (
            assembly_id SERIAL PRIMARY KEY,
            assembly_name VARCHAR(255) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE assembly_versions (
            assembly_version_id SERIAL PRIMARY KEY,
            assembly_id INTEGER NOT NULL REFERENCES assemblies (assembly_id),
            version_name VARCHAR(100) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE assembly_version_items (
            assembly_version_item_id SERIAL PRIMARY KEY,
            assembly_version_id INTEGER NOT NULL
                REFERENCES assembly_versions (assembly_version_id),
            product_id INTEGER NOT NULL REFERENCES items (item_id),
            amount INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_assembly_versions_assembly_id ON assembly_versions (assembly_id);"
    )
    op.execute(
        "CREATE INDEX ix_assembly_version_items_assembly_version_id "
        "ON assembly_version_items (assembly_version_id);"
    )
    op.execute(
        "CREATE INDEX ix_assembly_version_items_product_id "
        "ON assembly_version_items (product_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assembly_version_items;")
    op.execute("DROP TABLE IF EXISTS assembly_versions;")
    op.execute("DROP TABLE IF EXISTS assemblies;")

    op.execute(
        """
        CREATE TABLE assemblies (
            assembly_id SERIAL PRIMARY KEY,
            assembly_name VARCHAR(255) NOT NULL,
            version_name VARCHAR(100),
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE assembly_items (
            assembly_item_id SERIAL PRIMARY KEY,
            assembly_id INTEGER NOT NULL REFERENCES assemblies (assembly_id),
            product_id INTEGER NOT NULL REFERENCES items (item_id),
            amount INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
