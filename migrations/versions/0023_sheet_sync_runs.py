"""add sheet_sync_runs and sheet_sync_run_logs

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sheet_sync_runs (
            run_id SERIAL PRIMARY KEY,
            job VARCHAR(100) NOT NULL,
            started_at TIMESTAMP NOT NULL DEFAULT now(),
            finished_at TIMESTAMP,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            responses_seen INTEGER NOT NULL DEFAULT 0,
            pos_shipped INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sheet_sync_run_logs (
            log_id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES sheet_sync_runs (run_id) ON DELETE CASCADE,
            logged_at TIMESTAMP NOT NULL DEFAULT now(),
            level VARCHAR(10) NOT NULL,
            message TEXT NOT NULL
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sheet_sync_runs_job_started "
        "ON sheet_sync_runs (job, started_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sheet_sync_run_logs_run_id ON sheet_sync_run_logs (run_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sheet_sync_run_logs;")
    op.execute("DROP TABLE IF EXISTS sheet_sync_runs;")
