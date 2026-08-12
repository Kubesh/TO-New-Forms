from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from src.models import PurchaseOrder, PurchaseOrderLineItem


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
        .where(PurchaseOrder.customer_id == customer_id)
        .order_by(PurchaseOrder.order_date.desc().nulls_last(), PurchaseOrder.po_number)
    )
    return list(session.scalars(stmt).all())


def get_purchase_order(session: Session, po_id: int) -> PurchaseOrder | None:
    stmt = (
        select(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.customer),
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
