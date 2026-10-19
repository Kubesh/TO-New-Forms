from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased, selectinload

from src.models import Category, Item
from src.services.categories import load_category_chain


def get_item(session: Session, item_id: int) -> Item | None:
    stmt = (
        select(Item)
        .where(Item.item_id == item_id)
        .options(load_category_chain(selectinload(Item.category)))
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


# The item's subcategory (line) name for display, None when it sits directly
# under a top-level category. For an item in a sub sub category that's the
# sub sub category's parent. Needs Category (the item's category) and ParentCategory
# (its parent) joined.
ParentCategory = aliased(Category)
_SUBCATEGORY_LABEL = case(
    (ParentCategory.parent_id.isnot(None), ParentCategory.name),
    (Category.parent_id.isnot(None), Category.name),
    else_=None,
)


def _with_category_joins(stmt):
    return stmt.outerjoin(Category, Item.category_id == Category.category_id).outerjoin(
        ParentCategory, Category.parent_id == ParentCategory.category_id
    )


def list_sellable_item_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str, str | None]]:
    """(item_id, sku, name, subcategory) tuples for sellable items, for
    populating line-item SKU pickers. Items already on the PO
    (exclude_item_ids) are left out so they can't be added a second time."""
    stmt = _with_category_joins(
        select(Item.item_id, Item.sku, Item.name, _SUBCATEGORY_LABEL)
    ).where(Item.sellable.is_(True))
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]


def list_shipping_material_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str, str | None]]:
    """(item_id, sku, name, subcategory) tuples for shipping-material items."""
    stmt = _with_category_joins(
        select(Item.item_id, Item.sku, Item.name, _SUBCATEGORY_LABEL)
    ).where(Item.shipping_material.is_(True))
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]


def list_all_item_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str, str | None]]:
    """(item_id, sku, name, subcategory) tuples for every item, unfiltered -
    an assembly can consume or produce any item, not just sellable ones."""
    stmt = _with_category_joins(select(Item.item_id, Item.sku, Item.name, _SUBCATEGORY_LABEL))
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
    # Sort by top-level category name (the topmost of the item's category
    # and its ancestors) so cards group visually the same way regardless of
    # how deep an item sits.
    Grandparent = aliased(Category)
    stmt = (
        _with_category_joins(select(Item))
        .outerjoin(Grandparent, ParentCategory.parent_id == Grandparent.category_id)
        .options(load_category_chain(selectinload(Item.category)))
    )
    stmt = _apply_item_filters(stmt, query, category_ids, sellable)
    # Then by line (the second level), then the item's own category.
    line_name = case(
        (Grandparent.category_id.isnot(None), ParentCategory.name),
        (ParentCategory.category_id.isnot(None), Category.name),
        else_="",
    )
    stmt = stmt.order_by(
        func.coalesce(Grandparent.name, ParentCategory.name, Category.name),
        line_name,
        Category.name,
        Item.name,
    )
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).all())
