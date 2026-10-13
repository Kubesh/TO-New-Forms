"""create order_shipstation, one row per send of a PO to ShipStation

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-13

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One row per time a PO is sent, so a PO can be sent more than once and
    # the page can show when it last went. label_created_at / tracking_number
    # are filled in later by scripts/shipstation_sync.py once someone prints
    # the label in ShipStation - that is NOT the same as the order having
    # physically shipped.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS order_shipstation (
            order_shipstation_id SERIAL PRIMARY KEY,
            po_id INTEGER NOT NULL REFERENCES po_headers (po_id) ON DELETE CASCADE,
            shipstation_order_id BIGINT NOT NULL,
            order_key VARCHAR(100) NOT NULL,
            order_number VARCHAR(50),
            sent_at TIMESTAMP NOT NULL DEFAULT now(),
            label_created_at TIMESTAMP,
            tracking_number VARCHAR(100),
            carrier_code VARCHAR(50),
            last_checked_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_shipstation_po_id "
        "ON order_shipstation (po_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_shipstation_shipstation_order_id "
        "ON order_shipstation (shipstation_order_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS order_shipstation;")
