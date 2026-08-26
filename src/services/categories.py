from sqlalchemy import select
from sqlalchemy.orm import Session

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


def get_category_color_map(session: Session) -> dict[str, str]:
    """Top-level category name -> color, for the card-indicator color used
    everywhere categories are shown (Items, Inventory)."""
    stmt = (
        select(Category.name, Category.color)
        .where(Category.parent_id.is_(None))
        .where(Category.color.isnot(None))
    )
    return dict(session.execute(stmt).all())


def list_items_in_category(
    session: Session, category_name: str, subcategory_name: str | None = None
) -> list[Item]:
    stmt = select(Item).where(Item.category == category_name)
    if subcategory_name:
        stmt = stmt.where(Item.subcategory == subcategory_name)
    stmt = stmt.order_by(Item.subcategory, Item.name)
    return list(session.scalars(stmt).all())
