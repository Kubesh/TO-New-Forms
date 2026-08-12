from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Item


def list_item_choices(session: Session) -> list[tuple[int, str, str]]:
    """(item_id, sku, name) triples, for populating line-item SKU pickers."""
    stmt = select(Item.item_id, Item.sku, Item.name).order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]
