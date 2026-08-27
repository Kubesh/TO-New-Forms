from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Assembly, AssemblyVersion, Batch, BatchItem


def list_current_batches(session: Session) -> list[Batch]:
    """Batches still being worked on - released_at is null."""
    stmt = (
        select(Batch)
        .where(Batch.released_at.is_(None))
        .options(
            selectinload(Batch.version).selectinload(AssemblyVersion.assembly),
            selectinload(Batch.items),
        )
        .order_by(Batch.created_at.desc())
    )
    return list(session.scalars(stmt).all())


def get_batch(session: Session, batch_id: int) -> Batch | None:
    stmt = (
        select(Batch)
        .where(Batch.batch_id == batch_id)
        .options(
            selectinload(Batch.version).selectinload(AssemblyVersion.assembly),
            selectinload(Batch.parent).selectinload(Batch.version).selectinload(AssemblyVersion.assembly),
            selectinload(Batch.items).selectinload(BatchItem.product),
        )
    )
    return session.scalars(stmt).first()


def list_batch_choices(session: Session, exclude_batch_id: int | None = None) -> list[Batch]:
    """For a parent-batch picker - every batch, newest first."""
    stmt = (
        select(Batch)
        .options(selectinload(Batch.version).selectinload(AssemblyVersion.assembly))
        .order_by(Batch.created_at.desc())
    )
    if exclude_batch_id is not None:
        stmt = stmt.where(Batch.batch_id != exclude_batch_id)
    return list(session.scalars(stmt).all())


def create_batch(
    session: Session,
    version_id: int,
    batch_code: str,
    parent_id: int | None = None,
    expire_date: date | None = None,
    notes: str | None = None,
) -> Batch:
    batch = Batch(
        version_id=version_id,
        batch_code=batch_code,
        parent_id=parent_id,
        expire_date=expire_date,
        notes=notes,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def update_batch(session: Session, batch_id: int, **fields) -> Batch | None:
    batch = session.get(Batch, batch_id)
    if batch is None:
        return None
    for key, value in fields.items():
        setattr(batch, key, value)
    session.commit()
    session.refresh(batch)
    return batch


def release_batch(session: Session, batch_id: int) -> Batch | None:
    return update_batch(session, batch_id, released_at=datetime.utcnow())


def get_batch_item(session: Session, batch_item_id: int) -> BatchItem | None:
    return session.get(BatchItem, batch_item_id)


def add_batch_item(
    session: Session,
    batch_id: int,
    product_id: int,
    units: float,
    lot_number: str | None = None,
    notes: str | None = None,
) -> BatchItem:
    batch_item = BatchItem(
        batch_id=batch_id, product_id=product_id, units=units, lot_number=lot_number, notes=notes
    )
    session.add(batch_item)
    session.commit()
    session.refresh(batch_item)
    return batch_item


def update_batch_item(session: Session, batch_item_id: int, **fields) -> BatchItem | None:
    batch_item = session.get(BatchItem, batch_item_id)
    if batch_item is None:
        return None
    for key, value in fields.items():
        setattr(batch_item, key, value)
    session.commit()
    session.refresh(batch_item)
    return batch_item


def delete_batch_item(session: Session, batch_item_id: int) -> None:
    batch_item = session.get(BatchItem, batch_item_id)
    if batch_item is not None:
        session.delete(batch_item)
        session.commit()
