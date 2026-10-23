import time
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import OrderShipstation, PurchaseOrder
from src.services.order_types import shipstation_block_reason
from src.services.purchase_orders import get_purchase_order
from src.services.shipstation import (
    ShipStationError,
    configured_order_options,
    configured_shipping_method,
    get_labels_for_order,
    next_sequence,
    order_key_for,
    order_number_for,
    order_weight_lb,
    send_order,
)


def list_sends_for_po(session: Session, po_id: int) -> list[OrderShipstation]:
    """Every time this PO was sent to ShipStation, newest first."""
    stmt = (
        select(OrderShipstation)
        .where(OrderShipstation.po_id == po_id)
        .order_by(OrderShipstation.sent_at.desc(), OrderShipstation.order_shipstation_id.desc())
    )
    return list(session.scalars(stmt).all())


def record_send(
    session: Session, po: PurchaseOrder, shipstation_order: dict, order_key: str, order_number: str
) -> OrderShipstation:
    send = OrderShipstation(
        po_id=po.po_id,
        shipstation_order_id=int(shipstation_order["orderId"]),
        order_key=order_key,
        order_number=order_number,
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


# ShipStation allows 40 API calls a minute; 1.6s apart stays just under it.
SECONDS_BETWEEN_CALLS = 1.6


def check_all_labels(session: Session, on_progress=None) -> dict:
    """Asks ShipStation about every send that has no label yet (live POs only)
    and records what it finds. Returns {"checked", "found"}; raises
    ShipStationError (e.g. rate limit) after saving what was found so far.
    `on_progress(done, total)` is called after each order."""
    by_order: dict[int, list[OrderShipstation]] = defaultdict(list)
    for send in list_sends_awaiting_label(session, datetime.min):
        by_order[send.shipstation_order_id].append(send)
    found = 0
    for done, (order_id, sends) in enumerate(by_order.items(), start=1):
        if done > 1:
            time.sleep(SECONDS_BETWEEN_CALLS)
        if refresh_labels(session, order_id, sends):
            found += 1
        if on_progress:
            on_progress(done, len(by_order))
    return {"checked": len(by_order), "found": found}


def list_recent_sends(session: Session, limit: int = 50) -> list[tuple[OrderShipstation, str]]:
    """The latest sends across all POs, newest first, with each PO's number."""
    stmt = (
        select(OrderShipstation, PurchaseOrder.po_number)
        .join(PurchaseOrder, PurchaseOrder.po_id == OrderShipstation.po_id)
        .order_by(OrderShipstation.sent_at.desc(), OrderShipstation.order_shipstation_id.desc())
        .limit(limit)
    )
    return [(send, po_number) for send, po_number in session.execute(stmt).all()]


def send_po(session: Session, po_id: int) -> dict:
    """Sends a PO to ShipStation as a new order and records the send. Returns
    {"order", "shipping", "weight_lb", "missing_weight_skus"}; raises
    ShipStationError / ShipStationNotConfigured."""
    po = get_purchase_order(session, po_id)
    if po is None or po.voided or po.ship_date is not None:
        raise ShipStationError("This PO can't be sent - it's voided or already shipped.")
    if reason := shipstation_block_reason(po.order_type):
        raise ShipStationError(reason)
    existing_keys = {send.order_key for send in list_sends_for_po(session, po_id)}
    sequence = next_sequence(po, existing_keys)
    shipping = configured_shipping_method(session)
    order = send_order(po, sequence, shipping, configured_order_options(session))
    record_send(session, po, order, order_key_for(po, sequence), order_number_for(po, sequence))
    weight_lb, missing = order_weight_lb(po)
    return {"order": order, "shipping": shipping, "weight_lb": weight_lb, "missing_weight_skus": missing}
