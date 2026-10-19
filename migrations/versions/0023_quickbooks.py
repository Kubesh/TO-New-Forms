"""QuickBooks Online: the connection, and app <-> QuickBooks links

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The authorised QuickBooks company, one row per (environment, company).
    # Intuit refresh tokens rotate - every refresh returns a new one - so the
    # latest must be saved each time or the app is locked out.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS qbo_connection (
            qbo_connection_id SERIAL PRIMARY KEY,
            environment VARCHAR(20) NOT NULL,
            realm_id VARCHAR(40) NOT NULL,
            access_token TEXT NOT NULL,
            access_token_expires_at TIMESTAMP NOT NULL,
            refresh_token TEXT NOT NULL,
            refresh_token_expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_qbo_connection_env_realm UNIQUE (environment, realm_id)
        );
        """
    )
    # Links are keyed by realm (the QuickBooks company), not stored as a column
    # on customers/items: the same app customer has a different QuickBooks ID
    # in the sandbox company than in the real one, and both must be able to
    # coexist while the app moves from one to the other.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS qbo_customer_link (
            qbo_customer_link_id SERIAL PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers (customer_id) ON DELETE CASCADE,
            realm_id VARCHAR(40) NOT NULL,
            qbo_customer_id VARCHAR(40) NOT NULL,
            qbo_display_name VARCHAR(255),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_qbo_customer_link_customer_realm UNIQUE (customer_id, realm_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_qbo_customer_link_qbo_customer "
        "ON qbo_customer_link (realm_id, qbo_customer_id);"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS qbo_item_link (
            qbo_item_link_id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items (item_id) ON DELETE CASCADE,
            realm_id VARCHAR(40) NOT NULL,
            qbo_item_id VARCHAR(40) NOT NULL,
            qbo_item_name VARCHAR(255),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_qbo_item_link_item_realm UNIQUE (item_id, realm_id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS qbo_item_link;")
    op.execute("DROP TABLE IF EXISTS qbo_customer_link;")
    op.execute("DROP TABLE IF EXISTS qbo_connection;")
