from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Customer, OrderType

FALLBACK_ORDER_TYPE = "Direct"
CUSTOMER_TYPE_DEFAULTS = {"Distributor": "Distributor"}


def list_order_type_names(session: Session) -> list[str]:
    stmt = select(OrderType.name).order_by(OrderType.name)
    return list(session.scalars(stmt).all())


def list_order_type_choices(session: Session) -> list[tuple[int, str]]:
    stmt = select(OrderType.order_type_id, OrderType.name).order_by(OrderType.name)
    return [tuple(row) for row in session.execute(stmt).all()]


def resolve_default_order_type(customer: Customer | None) -> str:
    """The order type a new PO for this customer should start with:
    the customer's own explicit default if set, else a type driven by their
    customer_type (currently only Distributor customers default to
    Distributor), else Direct."""
    if customer is None:
        return FALLBACK_ORDER_TYPE
    if customer.default_order_type:
        return customer.default_order_type.name
    if customer.customer_type and customer.customer_type.name in CUSTOMER_TYPE_DEFAULTS:
        return CUSTOMER_TYPE_DEFAULTS[customer.customer_type.name]
    return FALLBACK_ORDER_TYPE


def is_faire_order(order_type: str | None) -> bool:
    """Faire orders are handled entirely in Faire: they are never sent to
    ShipStation or invoiced in QuickBooks. Matches "Faire", "Faire Order"..."""
    return "faire" in (order_type or "").strip().lower()


def shipstation_block_reason(order_type: str | None) -> str | None:
    """Why a PO of this order type is never sent to ShipStation, or None if it
    can be: Faire orders are handled in Faire, and Distributor orders ship LTL."""
    lowered = (order_type or "").strip().lower()
    if "faire" in lowered:
        return "Faire orders aren't sent to ShipStation."
    if "distributor" in lowered:
        return "Distributor orders ship LTL, so they aren't sent to ShipStation."
    return None
