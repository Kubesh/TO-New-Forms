from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Item


def list_sellable_item_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str]]:
    """(item_id, sku, name) triples for sellable items, for populating line-item
    SKU pickers. Items already on the PO (exclude_item_ids) are left out so
    they can't be added a second time."""
    stmt = select(Item.item_id, Item.sku, Item.name).where(Item.sellable.is_(True))
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]


def list_shipping_material_choices(
    session: Session, exclude_item_ids=None
) -> list[tuple[int, str, str]]:
    """(item_id, sku, name) triples for shipping-material items."""
    stmt = select(Item.item_id, Item.sku, Item.name).where(Item.shipping_material.is_(True))
    if exclude_item_ids:
        stmt = stmt.where(Item.item_id.notin_(exclude_item_ids))
    stmt = stmt.order_by(Item.sku)
    return [tuple(row) for row in session.execute(stmt).all()]
