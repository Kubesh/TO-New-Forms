from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import MAX_CATEGORY_DEPTH, Category, Item


def list_top_level_categories(session: Session) -> list[Category]:
    stmt = select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    return list(session.scalars(stmt).all())


def list_subcategories(session: Session, parent_id: int) -> list[Category]:
    stmt = select(Category).where(Category.parent_id == parent_id).order_by(Category.name)
    return list(session.scalars(stmt).all())


def get_category(session: Session, category_id: int) -> Category | None:
    return session.get(Category, category_id)


# Category (e.g. "Sellable Product") > subcategory (a line, e.g. "Drinking
# Chocolate") > form factor (e.g. "SUP"). The table is self-referencing, so
# this is only a limit we enforce here.
MAX_DEPTH = MAX_CATEGORY_DEPTH
LEVEL_LABELS = {1: "Category", 2: "Subcategory", 3: "Form factor"}


def load_category_chain(option):
    """Extends a loader option that ends at an item's category (e.g.
    selectinload(Item.category)) so every ancestor of that category is loaded
    too - category_path() walks them after the session has closed."""
    for _ in range(MAX_DEPTH):
        option = option.selectinload(Category.parent)
    return option


def category_depth(category: Category) -> int:
    """1 for a top-level category, 2 for a subcategory, 3 for a form factor."""
    depth = 1
    while category.parent is not None:
        category = category.parent
        depth += 1
    return depth


def category_path(category: Category | None) -> list[Category]:
    """The category's ancestors and itself, top-level first."""
    path = []
    while category is not None:
        path.append(category)
        category = category.parent
    return path[::-1]


def descendant_ids(session: Session, category_id: int) -> list[int]:
    """category_id and the id of every category under it, at any depth."""
    parents = dict(session.execute(select(Category.category_id, Category.parent_id)).all())
    found = {category_id}
    changed = True
    while changed:
        changed = False
        for child_id, parent_id in parents.items():
            if parent_id in found and child_id not in found:
                found.add(child_id)
                changed = True
    return sorted(found)


def create_category(
    session: Session, name: str, parent_id: int | None = None, color: str | None = None
) -> Category:
    if parent_id is not None:
        parent = session.get(Category, parent_id)
        if parent is None:
            raise ValueError("Parent category not found.")
        if category_depth(parent) >= MAX_DEPTH:
            raise ValueError(f"Categories can only go {MAX_DEPTH} levels deep.")
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
    """The top-level category's name for any Category row - itself if it's
    already top-level, otherwise its topmost ancestor's."""
    path = category_path(category)
    return path[0].name if path else None


def subcategory_name(category: Category | None) -> str | None:
    """The subcategory (line) name - the second level of the path - or None if
    the row is a top-level category (or there's no category at all)."""
    path = category_path(category)
    return path[1].name if len(path) > 1 else None


def form_factor_name(category: Category | None) -> str | None:
    """The form factor (third level) name, or None if there isn't one."""
    path = category_path(category)
    return path[2].name if len(path) > 2 else None


def list_items_in_category(session: Session, category_id: int) -> list[Item]:
    """Every item directly under category_id or under any category below it."""
    if session.get(Category, category_id) is None:
        return []

    stmt = (
        select(Item)
        .where(Item.category_id.in_(descendant_ids(session, category_id)))
        .options(selectinload(Item.category))
        .order_by(Item.category_id, Item.name)
    )
    return list(session.scalars(stmt).all())


def move_items_to_categories(session: Session, moves: dict[int, int]) -> None:
    """Sets each item's category: moves is {item_id: category_id}."""
    for item_id, category_id in moves.items():
        item = session.get(Item, item_id)
        if item is not None:
            item.category_id = category_id
    session.commit()
