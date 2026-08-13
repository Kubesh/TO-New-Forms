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
