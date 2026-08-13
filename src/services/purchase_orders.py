from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from src.models import Customer, PurchaseOrder, PurchaseOrderLineItem


def _apply_po_filters(stmt, query: str | None = None, customer_id: int | None = None):
    if query:
        stmt = stmt.where(PurchaseOrder.po_number.ilike(f"%{query}%"))
    if customer_id is not None:
        stmt = stmt.where(PurchaseOrder.customer_id == customer_id)
    return stmt


def count_purchase_orders(
    session: Session, query: str | None = None, customer_id: int | None = None
) -> int:
    stmt = _apply_po_filters(
        select(func.count()).select_from(PurchaseOrder), query, customer_id
    )
    return session.scalar(stmt) or 0


def search_purchase_orders(
    session: Session,
    query: str | None = None,
    customer_id: int | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[PurchaseOrder]:
    stmt = select(PurchaseOrder).options(joinedload(PurchaseOrder.customer))
    stmt = _apply_po_filters(stmt, query, customer_id)
    stmt = stmt.order_by(PurchaseOrder.order_date.desc().nulls_last(), PurchaseOrder.po_number)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).unique().all())


def list_purchase_orders_for_customer(
    session: Session, customer_id: int
) -> list[PurchaseOrder]:
    stmt = (
        select(PurchaseOrder)
        .options(joinedload(PurchaseOrder.customer))
        .where(PurchaseOrder.customer_id == customer_id)
        .order_by(PurchaseOrder.order_date.desc().nulls_last(), PurchaseOrder.po_number)
    )
    return list(session.scalars(stmt).unique().all())


def get_purchase_order(session: Session, po_id: int) -> PurchaseOrder | None:
    stmt = (
        select(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.customer).joinedload(Customer.customer_type),
            joinedload(PurchaseOrder.customer).joinedload(Customer.default_order_type),
            joinedload(PurchaseOrder.line_items).joinedload(PurchaseOrderLineItem.item),
        )
        .where(PurchaseOrder.po_id == po_id)
    )
    return session.scalars(stmt).unique().first()


def get_po_line_item_stats(session: Session, po_ids) -> dict[int, tuple[int, object]]:
    """po_id -> (distinct SKU count, total quantity) for the given POs."""
    po_ids = list(po_ids)
    if not po_ids:
        return {}
    stmt = (
        select(
            PurchaseOrderLineItem.po_id,
            func.count(func.distinct(PurchaseOrderLineItem.sku)),
            func.sum(PurchaseOrderLineItem.quantity),
        )
        .where(PurchaseOrderLineItem.po_id.in_(po_ids))
        .group_by(PurchaseOrderLineItem.po_id)
    )
    return {po_id: (sku_count, total_units) for po_id, sku_count, total_units in session.execute(stmt)}


def get_non_voided_po_counts(session: Session, customer_ids) -> dict[int, int]:
    """customer_id -> count of that customer's non-voided POs."""
    customer_ids = list(customer_ids)
    if not customer_ids:
        return {}
    stmt = (
        select(PurchaseOrder.customer_id, func.count())
        .where(PurchaseOrder.customer_id.in_(customer_ids), PurchaseOrder.voided.is_(False))
        .group_by(PurchaseOrder.customer_id)
    )
    return {customer_id: count for customer_id, count in session.execute(stmt)}


def create_purchase_order(session: Session, **fields) -> PurchaseOrder:
    po = PurchaseOrder(**fields)
    session.add(po)
    session.commit()
    session.refresh(po)
    return po


def delete_purchase_order(session: Session, po_id: int) -> bool:
    """Deletes a PO (and its line items / shipping materials, via cascade).
    Only allowed once the PO is voided and was never shipped - callers should
    already be enforcing that in the UI, but it's re-checked here too."""
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        return False
    if not po.voided or po.ship_date is not None:
        return False
    session.delete(po)
    session.commit()
    return True


def update_purchase_order(session: Session, po_id: int, **fields) -> PurchaseOrder | None:
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        return None
    for key, value in fields.items():
        setattr(po, key, value)
    session.commit()
    session.refresh(po)
    return po


def update_line_item_quantities(session: Session, quantities: dict[int, int]) -> None:
    """line_item_id -> new current quantity. original_quantity is untouched."""
    if not quantities:
        return
    line_items = session.scalars(
        select(PurchaseOrderLineItem).where(PurchaseOrderLineItem.line_item_id.in_(quantities.keys()))
    )
    for line_item in line_items:
        line_item.quantity = quantities[line_item.line_item_id]
    session.commit()


def add_line_item(
    session: Session, po_id: int, item_id: int, sku: str, quantity: int
) -> PurchaseOrderLineItem:
    line_item = PurchaseOrderLineItem(
        po_id=po_id,
        item_id=item_id,
        sku=sku,
        quantity=quantity,
        original_quantity=quantity,
    )
    session.add(line_item)
    session.commit()
    session.refresh(line_item)
    return line_item
