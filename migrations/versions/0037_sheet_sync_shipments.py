"""add sheet_sync_shipments

One row per PO a sync script marked shipped, kept past the 30-day pruning of
sheet_sync_runs so per-day totals don't lose history.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("sheet_sync_shipments"):
        return
    op.execute(
        """
        CREATE TABLE sheet_sync_shipments (
            shipment_id SERIAL PRIMARY KEY,
            job VARCHAR(100) NOT NULL,
            run_id INTEGER REFERENCES sheet_sync_runs (run_id) ON DELETE SET NULL,
            po_id INTEGER REFERENCES po_headers (po_id) ON DELETE SET NULL,
            po_number VARCHAR(50) NOT NULL,
            shipped_at TIMESTAMP NOT NULL,
            marked_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_sheet_sync_shipments_job_shipped ON sheet_sync_shipments (job, shipped_at DESC);"
    )
    op.execute("CREATE INDEX ix_sheet_sync_shipments_run_id ON sheet_sync_shipments (run_id);")
    # Carry over what earlier runs already shipped, from their log lines
    # ("<form timestamp>: shipped PO <number>"). po_id can't be recovered.
    op.execute(
        r"""
        INSERT INTO sheet_sync_shipments (job, run_id, po_number, shipped_at, marked_at)
        SELECT r.job, l.run_id, m[2], m[1]::timestamp, COALESCE(r.finished_at, r.started_at)
        FROM sheet_sync_run_logs l
        JOIN sheet_sync_runs r ON r.run_id = l.run_id,
        LATERAL regexp_match(
            l.message, '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}): shipped PO (.+)$'
        ) AS m
        WHERE m IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sheet_sync_shipments;")
