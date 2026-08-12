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
