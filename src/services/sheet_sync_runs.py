from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.models import SheetSyncRun, SheetSyncShipment

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


def list_runs_for_day(session: Session, job: str, day: date) -> list[SheetSyncRun]:
    """Every run that started on this day, oldest first."""
    start = datetime.combine(day, time.min)
    stmt = (
        select(SheetSyncRun)
        .where(
            SheetSyncRun.job == job,
            SheetSyncRun.started_at >= start,
            SheetSyncRun.started_at < start + timedelta(days=1),
        )
        .options(selectinload(SheetSyncRun.logs))
        .order_by(SheetSyncRun.started_at)
    )
    return list(session.scalars(stmt).all())


def shipped_per_day(session: Session, job: str, days: int) -> list[tuple[date, int]]:
    """POs shipped per ship-date day for the last `days` days including today,
    oldest first, with 0 for days nothing shipped."""
    first = date.today() - timedelta(days=days - 1)
    day = func.date(SheetSyncShipment.shipped_at)
    rows = session.execute(
        select(day, func.count())
        .where(SheetSyncShipment.job == job, SheetSyncShipment.shipped_at >= datetime.combine(first, time.min))
        .group_by(day)
    ).all()
    counts = {d: n for d, n in rows}
    return [(first + timedelta(days=i), counts.get(first + timedelta(days=i), 0)) for i in range(days)]


def list_shipments(
    session: Session, job: str, po_search: str = "", limit: int = 50, offset: int = 0
) -> tuple[list[SheetSyncShipment], int]:
    """(one page of shipments newest first, total matching)."""
    where = [SheetSyncShipment.job == job]
    search = po_search.strip().lstrip("#")
    if search:
        where.append(SheetSyncShipment.po_number.ilike(f"%{search}%"))
    total = session.scalar(select(func.count()).select_from(SheetSyncShipment).where(*where)) or 0
    rows = session.scalars(
        select(SheetSyncShipment)
        .where(*where)
        .order_by(SheetSyncShipment.shipped_at.desc(), SheetSyncShipment.shipment_id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total
