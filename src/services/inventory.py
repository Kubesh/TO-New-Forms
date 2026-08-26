from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.models import Category, InventoryCount, InventoryCountItem, Item


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
                order_by=(
                    InventoryCountItem.created_at.desc(),
                    InventoryCountItem.inventory_count_item_id.desc(),
                ),
            )
            .label("rank"),
        )
    ).subquery()
    return select(ranked.c.item_id, ranked.c.counted).where(ranked.c.rank == 1).subquery()


def list_inventory(session: Session, query: str | None = None) -> list[tuple[Item, int | None]]:
    """(item, current_on_hand) pairs - current_on_hand is None for an item
    that's never been counted."""
    latest = _latest_count_subquery()
    TopCategory = Category.__table__.alias("top_category")
    stmt = (
        select(Item, latest.c.counted)
        .outerjoin(latest, latest.c.item_id == Item.item_id)
        .outerjoin(Category, Item.category_id == Category.category_id)
        .outerjoin(TopCategory, Category.parent_id == TopCategory.c.category_id)
        .options(selectinload(Item.category).selectinload(Category.parent))
    )
    if query:
        stmt = stmt.where(Item.name.ilike(f"%{query}%") | Item.sku.ilike(f"%{query}%"))
    stmt = stmt.order_by(
        Item.sellable.desc(),
        func.coalesce(TopCategory.c.name, Category.name),
        Category.name,
        Item.name,
    )
    return [tuple(row) for row in session.execute(stmt).all()]


def get_current_on_hand(session: Session, item_id: int) -> int | None:
    latest = _latest_count_subquery()
    stmt = select(latest.c.counted).where(latest.c.item_id == item_id)
    return session.scalar(stmt)


def get_last_count(session: Session, item_id: int) -> InventoryCountItem | None:
    stmt = (
        select(InventoryCountItem)
        .where(InventoryCountItem.item_id == item_id)
        .order_by(
            InventoryCountItem.created_at.desc(),
            InventoryCountItem.inventory_count_item_id.desc(),
        )
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_counts_for_item(session: Session, item_id: int) -> list[InventoryCountItem]:
    stmt = (
        select(InventoryCountItem)
        .where(InventoryCountItem.item_id == item_id)
        .order_by(
            InventoryCountItem.created_at.desc(),
            InventoryCountItem.inventory_count_item_id.desc(),
        )
    )
    return list(session.scalars(stmt).all())


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
