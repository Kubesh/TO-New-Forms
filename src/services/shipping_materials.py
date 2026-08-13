from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.models import OrderShippingMaterial


def list_shipping_materials_for_po(session: Session, po_id: int) -> list[OrderShippingMaterial]:
    stmt = (
        select(OrderShippingMaterial)
        .options(joinedload(OrderShippingMaterial.item))
        .where(OrderShippingMaterial.po_id == po_id)
        .order_by(OrderShippingMaterial.order_shipping_material_id)
    )
    return list(session.scalars(stmt).unique().all())


def replace_shipping_materials(
    session: Session, po_id: int, entries: list[tuple[int, int]]
) -> None:
    """entries: (item_id, quantity) pairs. Replaces the PO's full shipping-material
    list - this table has no original/current tracking, it just reflects
    what's currently being used, so a full replace on every save keeps it
    simple. Zero/negative quantities are dropped rather than stored."""
    session.query(OrderShippingMaterial).filter(OrderShippingMaterial.po_id == po_id).delete(
        synchronize_session=False
    )
    for item_id, quantity in entries:
        if quantity <= 0:
            continue
        session.add(OrderShippingMaterial(po_id=po_id, item_id=item_id, quantity=quantity))
    session.commit()
