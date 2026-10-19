"""QuickBooks invoices created from POs

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One row per attempt to create a QuickBooks invoice from a PO. 'pending'
    # is written before the call, so an attempt whose outcome is unknown (the
    # connection dropped) can be retried with the same request_id and
    # QuickBooks hands back the original invoice instead of making a second.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS qbo_invoices (
            qbo_invoice_record_id SERIAL PRIMARY KEY,
            po_id INTEGER NOT NULL REFERENCES po_headers (po_id) ON DELETE CASCADE,
            realm_id VARCHAR(40) NOT NULL,
            request_id VARCHAR(64) NOT NULL,
            status VARCHAR(20) NOT NULL,
            qbo_customer_id VARCHAR(40),
            qbo_invoice_id VARCHAR(40),
            doc_number VARCHAR(40),
            total_amount NUMERIC(12, 2),
            error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT ck_qbo_invoices_status CHECK (status IN ('pending', 'created', 'failed'))
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_qbo_invoices_po ON qbo_invoices (po_id);")
    # A PO has at most one live (created) invoice per QuickBooks company.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_qbo_invoices_created ON qbo_invoices "
        "(po_id, realm_id) WHERE status = 'created';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS qbo_invoices;")
