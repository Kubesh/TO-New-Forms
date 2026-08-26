from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import InventoryCount, InventoryCountItem, Item


def _latest_count_subquery():
    """One row per item_id: its most recent InventoryCountItem.counted
    value, via row_number() so this works identically on Postgres and
    SQLite rather than relying on a DISTINCT ON (Postgres-only)."""
    ranked = (
        select(
            InventoryCountItem.item_id,
            InventoryCountItem.counted,
            func.row_number()
            .over(
                partition_by=InventoryCountItem.item_id,
                order_by=InventoryCountItem.created_at.desc(),
            )
            .label("rank"),
        )
    ).subquery()
    return select(ranked.c.item_id, ranked.c.counted).where(ranked.c.rank == 1).subquery()


def list_inventory(
    session: Session,
    query: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
) -> list[tuple[Item, int | None]]:
    """(item, current_on_hand) pairs - current_on_hand is None for an item
    that's never been counted."""
    latest = _latest_count_subquery()
    stmt = select(Item, latest.c.counted).outerjoin(latest, latest.c.item_id == Item.item_id)
    if query:
        stmt = stmt.where(Item.name.ilike(f"%{query}%") | Item.sku.ilike(f"%{query}%"))
    if category:
        stmt = stmt.where(Item.category == category)
    if subcategory:
        stmt = stmt.where(Item.subcategory == subcategory)
    stmt = stmt.order_by(Item.category, Item.subcategory, Item.name)
    return [tuple(row) for row in session.execute(stmt).all()]


def get_current_on_hand(session: Session, item_id: int) -> int | None:
    latest = _latest_count_subquery()
    stmt = select(latest.c.counted).where(latest.c.item_id == item_id)
    return session.scalar(stmt)


def create_inventory_count(session: Session, counts: list[dict]) -> InventoryCount:
    """counts: [{"item_id": ..., "counted": ..., "notes": ...}, ...] for
    just the items actually touched this session - untouched rows aren't
    passed in at all."""
    inventory_count = InventoryCount()
    session.add(inventory_count)
    session.flush()  # populate inventory_count_id for the child rows below

    for entry in counts:
        session.add(
            InventoryCountItem(
                inventory_count_id=inventory_count.inventory_count_id,
                item_id=entry["item_id"],
                counted=entry["counted"],
                notes=entry.get("notes") or None,
            )
        )
    session.commit()
    session.refresh(inventory_count)
    return inventory_count
