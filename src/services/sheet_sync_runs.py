from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import SheetSyncRun

SHIPPED_FORM_JOB = "shipped_from_form"


def get_last_run(session: Session, job: str) -> SheetSyncRun | None:
    stmt = (
        select(SheetSyncRun)
        .where(SheetSyncRun.job == job)
        .options(selectinload(SheetSyncRun.logs))
        .order_by(SheetSyncRun.started_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_recent_runs(session: Session, job: str, limit: int = 50) -> list[SheetSyncRun]:
    stmt = (
        select(SheetSyncRun)
        .where(SheetSyncRun.job == job)
        .options(selectinload(SheetSyncRun.logs))
        .order_by(SheetSyncRun.started_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())
