from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from src.models import Category, Item


def get_item(session: Session, item_id: int) -> Item | None:
    stmt = (
        select(Item)
        .where(Item.item_id == item_id)
        .options(selectinload(Item.category).selectinload(Category.parent))
    )
    return session.scalars(stmt).first()


def update_item(session: Session, item_id: int, **fields) -> Item | None:
    item = session.get(Item, item_id)
    if item is None:
        return None
    for key, value in fields.items():
        setattr(item, key, value)
    session.commit()
    session.refresh(item)
    return item


def create_item(session: Session, sku: str, name: str, **fields) -> Item:
    item = Item(sku=sku, name=name, **fields)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


# A subcategory-only display label (None when the item's category is a
# top-level row with no subcategory) - matches the old items.subcategory
# column's semantics, for callers that only want that one string.
_SUBCATEGORY_LABEL = case((Category.parent_id.isnot(None), Category.name), else_=None)


def list_sellable_item_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str, str | None]]:
    """(item_id, sku, name, subcategory) tuples for sellable items, for
    populating line-item SKU pickers. Items already on the PO
    (exclude_item_ids) are left out so they can't be added a second time."""
    stmt = (
        select(Item.item_id, Item.sku, Item.name, _SUBCATEGORY_LABEL)
        .outerjoin(Category, Item.category_id == Category.category_id)
        .where(Item.sellable.is_(True))
    )
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]


def list_shipping_material_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str, str | None]]:
    """(item_id, sku, name, subcategory) tuples for shipping-material items."""
    stmt = (
        select(Item.item_id, Item.sku, Item.name, _SUBCATEGORY_LABEL)
        .outerjoin(Category, Item.category_id == Category.category_id)
        .where(Item.shipping_material.is_(True))
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
    stmt = select(Item.item_id, Item.sku, Item.name, _SUBCATEGORY_LABEL).outerjoin(
        Category, Item.category_id == Category.category_id
    )
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]


def _apply_item_filters(
    stmt,
    query: str | None = None,
    category_ids: list[int] | None = None,
    sellable: bool | None = None,
):
    if query:
        stmt = stmt.where(Item.name.ilike(f"%{query}%") | Item.sku.ilike(f"%{query}%"))
    if category_ids:
        stmt = stmt.where(Item.category_id.in_(category_ids))
    if sellable is not None:
        stmt = stmt.where(Item.sellable.is_(sellable))
    return stmt


def count_items(
    session: Session,
    query: str | None = None,
    category_ids: list[int] | None = None,
    sellable: bool | None = None,
) -> int:
    stmt = _apply_item_filters(
        select(func.count()).select_from(Item), query, category_ids, sellable
    )
    return session.scalar(stmt) or 0


def search_items(
    session: Session,
    query: str | None = None,
    category_ids: list[int] | None = None,
    sellable: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Item]:
    # Sort by top-level category name (a subcategory's parent's name, or
    # its own name if it has none) so cards group visually the same way
    # regardless of whether an item sits directly under a top-level
    # category or one of its subcategories.
    TopCategory = Category.__table__.alias("top_category")
    stmt = (
        select(Item)
        .outerjoin(Category, Item.category_id == Category.category_id)
        .outerjoin(TopCategory, Category.parent_id == TopCategory.c.category_id)
        .options(selectinload(Item.category).selectinload(Category.parent))
    )
    stmt = _apply_item_filters(stmt, query, category_ids, sellable)
    stmt = stmt.order_by(
        func.coalesce(TopCategory.c.name, Category.name), Category.name, Item.name
    )
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).all())
