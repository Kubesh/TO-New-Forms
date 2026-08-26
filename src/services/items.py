from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import Item


def get_item(session: Session, item_id: int) -> Item | None:
    return session.get(Item, item_id)


def update_item(session: Session, item_id: int, **fields) -> Item | None:
    item = session.get(Item, item_id)
    if item is None:
        return None
    for key, value in fields.items():
        setattr(item, key, value)
    session.commit()
    session.refresh(item)
    return item


def list_sellable_item_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str, str | None]]:
    """(item_id, sku, name, subcategory) tuples for sellable items, for
    populating line-item SKU pickers. Items already on the PO
    (exclude_item_ids) are left out so they can't be added a second time."""
    stmt = select(Item.item_id, Item.sku, Item.name, Item.subcategory).where(
        Item.sellable.is_(True)
    )
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]


def list_shipping_material_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str, str | None]]:
    """(item_id, sku, name, subcategory) tuples for shipping-material items."""
    stmt = select(Item.item_id, Item.sku, Item.name, Item.subcategory).where(
        Item.shipping_material.is_(True)
    )
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]


def list_all_item_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str, str | None]]:
    """(item_id, sku, name, subcategory) tuples for every item, unfiltered -
    an assembly can consume or produce any item, not just sellable ones."""
    stmt = select(Item.item_id, Item.sku, Item.name, Item.subcategory)
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]


def list_distinct_categories(session: Session) -> list[str]:
    stmt = (
        select(Item.category)
        .where(Item.category.isnot(None))
        .distinct()
        .order_by(Item.category)
    )
    return list(session.scalars(stmt).all())


def list_distinct_subcategories(session: Session, category: str | None = None) -> list[str]:
    stmt = select(Item.subcategory).where(Item.subcategory.isnot(None)).distinct()
    if category:
        stmt = stmt.where(Item.category == category)
    stmt = stmt.order_by(Item.subcategory)
    return list(session.scalars(stmt).all())


def _apply_item_filters(
    stmt,
    query: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    sellable: bool | None = None,
):
    if query:
        stmt = stmt.where(Item.name.ilike(f"%{query}%") | Item.sku.ilike(f"%{query}%"))
    if category:
        stmt = stmt.where(Item.category == category)
    if subcategory:
        stmt = stmt.where(Item.subcategory == subcategory)
    if sellable is not None:
        stmt = stmt.where(Item.sellable.is_(sellable))
    return stmt


def count_items(
    session: Session,
    query: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    sellable: bool | None = None,
) -> int:
    stmt = _apply_item_filters(
        select(func.count()).select_from(Item), query, category, subcategory, sellable
    )
    return session.scalar(stmt) or 0


def search_items(
    session: Session,
    query: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    sellable: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Item]:
    stmt = _apply_item_filters(select(Item), query, category, subcategory, sellable)
    stmt = stmt.order_by(Item.category, Item.subcategory, Item.name)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).all())
