from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Category, Item


def list_top_level_categories(session: Session) -> list[Category]:
    stmt = select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    return list(session.scalars(stmt).all())


def list_subcategories(session: Session, parent_id: int) -> list[Category]:
    stmt = select(Category).where(Category.parent_id == parent_id).order_by(Category.name)
    return list(session.scalars(stmt).all())


def get_category(session: Session, category_id: int) -> Category | None:
    return session.get(Category, category_id)


def create_category(
    session: Session, name: str, parent_id: int | None = None, color: str | None = None
) -> Category:
    category = Category(name=name, parent_id=parent_id, color=color)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def update_category(session: Session, category_id: int, **fields) -> Category | None:
    category = session.get(Category, category_id)
    if category is None:
        return None
    for key, value in fields.items():
        setattr(category, key, value)
    session.commit()
    session.refresh(category)
    return category


def top_level_category_name(category: Category | None) -> str | None:
    """The top-level category name for any Category row - itself if it's
    already top-level, its parent's name if it's a subcategory."""
    if category is None:
        return None
    return category.parent.name if category.parent_id else category.name


def subcategory_name(category: Category | None) -> str | None:
    """The subcategory name, or None if the row is a top-level category (or
    there's no category at all) - matches the old items.subcategory column,
    which was never set just because a top-level category was."""
    if category is None or category.parent_id is None:
        return None
    return category.name


def list_items_in_category(session: Session, category_id: int) -> list[Item]:
    """Every item directly under category_id, or under any of its
    subcategories if category_id is itself a top-level category."""
    category = session.get(Category, category_id)
    if category is None:
        return []

    if category.parent_id is None:
        subcategory_ids = [
            sub.category_id for sub in list_subcategories(session, category_id)
        ]
        category_ids = [category_id] + subcategory_ids
    else:
        category_ids = [category_id]

    stmt = (
        select(Item)
        .where(Item.category_id.in_(category_ids))
        .options(selectinload(Item.category))
        .order_by(Item.category_id, Item.name)
    )
    return list(session.scalars(stmt).all())
