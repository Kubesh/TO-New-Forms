from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import OrderShipstation, PurchaseOrder
from src.services.shipstation import get_labels_for_order


def list_sends_for_po(session: Session, po_id: int) -> list[OrderShipstation]:
    """Every time this PO was sent to ShipStation, newest first."""
    stmt = (
        select(OrderShipstation)
        .where(OrderShipstation.po_id == po_id)
        .order_by(OrderShipstation.sent_at.desc(), OrderShipstation.order_shipstation_id.desc())
    )
    return list(session.scalars(stmt).all())


def record_send(session: Session, po: PurchaseOrder, shipstation_order: dict, order_key: str) -> OrderShipstation:
    send = OrderShipstation(
        po_id=po.po_id,
        shipstation_order_id=int(shipstation_order["orderId"]),
        order_key=order_key,
        order_number=po.po_number,
        sent_at=datetime.now(),
    )
    session.add(send)
    session.commit()
    session.refresh(send)
    return send


def list_sends_awaiting_label(session: Session, since: datetime) -> list[OrderShipstation]:
    """Sends with no label recorded yet, for POs that are still live (not
    voided, no ship date), sent on or after `since`. What the sync script
    polls ShipStation about."""
    stmt = (
        select(OrderShipstation)
        .join(PurchaseOrder, PurchaseOrder.po_id == OrderShipstation.po_id)
        .where(
            OrderShipstation.label_created_at.is_(None),
            OrderShipstation.sent_at >= since,
            PurchaseOrder.voided.is_(False),
            PurchaseOrder.ship_date.is_(None),
        )
        .order_by(OrderShipstation.sent_at)
    )
    return list(session.scalars(stmt).all())


def refresh_labels(session: Session, shipstation_order_id: int, sends: list[OrderShipstation]) -> bool:
    """Asks ShipStation whether the order has a label yet and, if so, records
    its label time / tracking / carrier on every given send row. Returns True
    if a label was found. Shared by scripts/shipstation_sync.py and the PO
    page's "Check for label" button."""
    labels = get_labels_for_order(shipstation_order_id)
    now = datetime.now()
    for send in sends:
        send.last_checked_at = now
    if labels:
        # An order can have several labels (multiple packages); record the
        # earliest one's tracking.
        label = min(labels, key=lambda l: l["label_created_at"] or datetime.max)
        for send in sends:
            send.label_created_at = label["label_created_at"]
            send.tracking_number = label["tracking_number"]
            send.carrier_code = label["carrier_code"]
    session.commit()
    return bool(labels)
