import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from src.models import Customer, CustomerContact, CustomerType, PurchaseOrder

PHONE_MIN_DIGITS = 10


def format_phone_number(raw: str) -> tuple[str | None, str | None]:
    """Normalize a phone number into our canonical mask.

    Returns (formatted, error) - exactly one of which is not None. Only
    digits are counted; everything else typed in (spaces, dashes, parens,
    a leading +) is ignored.

    - 10 digits  -> 000-000-0000
    - 11+ digits -> +<country code> 000-000-0000, where everything before
      the trailing 10 digits becomes the country code, e.g. 11 digits ->
      "+0 000-000-0000", 13 digits -> "+000 000-000-0000".
    - Under 10 digits is rejected rather than guessed at.
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) < PHONE_MIN_DIGITS:
        return None, f"Phone number must have at least {PHONE_MIN_DIGITS} digits."
    local = digits[-PHONE_MIN_DIGITS:]
    formatted_local = f"{local[0:3]}-{local[3:6]}-{local[6:10]}"
    country_code = digits[:-PHONE_MIN_DIGITS]
    if country_code:
        return f"+{country_code} {formatted_local}", None
    return formatted_local, None


def format_postal_code(raw: str) -> str | None:
    """Normalize a postal code by its length, matching common formats:

    - 5 characters -> 00000 (US ZIP)
    - 6 characters -> XXX XXX (Canadian postal code)
    - 9 characters -> 00000-0000 (US ZIP+4)
    - any other length -> left as typed, just cleaned up

    Unlike phone numbers, no length is rejected here - this is formatting
    only, not validation.
    """
    cleaned = re.sub(r"[^0-9A-Za-z]", "", raw).upper()
    if not cleaned:
        return None
    if len(cleaned) == 5:
        return cleaned
    if len(cleaned) == 6:
        return f"{cleaned[:3]} {cleaned[3:]}"
    if len(cleaned) == 9:
        return f"{cleaned[:5]}-{cleaned[5:]}"
    return cleaned


def list_customer_types(session: Session) -> list[CustomerType]:
    stmt = select(CustomerType).order_by(CustomerType.name)
    return list(session.scalars(stmt).all())


DEFAULT_DUE_DATE_DAYS = 14
DUE_DATE_DAYS_BY_CUSTOMER_TYPE = {"Chain": 7, "Distributor": 21}


def resolve_due_date_days(customer: Customer | None) -> int:
    """Default PO due-date offset in days: 14 for everyone, 7 for chains,
    21 for distributors, keyed off the customer's customer_type."""
    if customer is None or customer.customer_type is None:
        return DEFAULT_DUE_DATE_DAYS
    return DUE_DATE_DAYS_BY_CUSTOMER_TYPE.get(customer.customer_type.name, DEFAULT_DUE_DATE_DAYS)


def get_duplicate_customer_names(session: Session) -> set[str]:
    """Customer names that appear on more than one customer record."""
    stmt = (
        select(Customer.customer_name)
        .group_by(Customer.customer_name)
        .having(func.count() > 1)
    )
    return set(session.scalars(stmt).all())


def _apply_customer_filters(
    stmt,
    query: str | None = None,
    customer_type_id: int | None = None,
    shipping_state: str | None = None,
    chain_name: str | None = None,
    has_ordered: bool | None = None,
    show_archived: bool = False,
):
    if query:
        stmt = stmt.where(Customer.customer_name.ilike(f"%{query}%"))
    if customer_type_id is not None:
        stmt = stmt.where(Customer.customer_type_id == customer_type_id)
    if shipping_state:
        stmt = stmt.where(Customer.shipping_state == shipping_state)
    if chain_name:
        stmt = stmt.where(Customer.notes == chain_name)
    if has_ordered:
        stmt = stmt.where(
            Customer.customer_id.in_(
                select(PurchaseOrder.customer_id).where(PurchaseOrder.customer_id.isnot(None))
            )
        )
    stmt = stmt.where(Customer.archived.is_(show_archived))
    return stmt


def count_customers(
    session: Session,
    query: str | None = None,
    customer_type_id: int | None = None,
    shipping_state: str | None = None,
    chain_name: str | None = None,
    has_ordered: bool | None = None,
    show_archived: bool = False,
) -> int:
    stmt = _apply_customer_filters(
        select(func.count()).select_from(Customer),
        query,
        customer_type_id,
        shipping_state,
        chain_name,
        has_ordered,
        show_archived,
    )
    return session.scalar(stmt) or 0


def search_customers(
    session: Session,
    query: str | None = None,
    customer_type_id: int | None = None,
    shipping_state: str | None = None,
    chain_name: str | None = None,
    has_ordered: bool | None = None,
    show_archived: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[Customer]:
    stmt = select(Customer).options(
        joinedload(Customer.customer_type),
        joinedload(Customer.parent),
    )
    stmt = _apply_customer_filters(
        stmt, query, customer_type_id, shipping_state, chain_name, has_ordered, show_archived
    )
    stmt = stmt.order_by(Customer.customer_name)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).unique().all())


def list_distinct_shipping_states(session: Session) -> list[str]:
    stmt = (
        select(Customer.shipping_state)
        .where(Customer.shipping_state.isnot(None))
        .distinct()
        .order_by(Customer.shipping_state)
    )
    return list(session.scalars(stmt).all())


def list_distinct_chain_names(session: Session) -> list[str]:
    stmt = (
        select(Customer.notes)
        .where(Customer.notes.isnot(None))
        .distinct()
        .order_by(Customer.notes)
    )
    return list(session.scalars(stmt).all())


def list_customer_choices(
    session: Session, exclude_customer_id: int | None = None
) -> list[tuple[int, str]]:
    """(customer_id, customer_name) pairs, for populating parent-account pickers."""
    stmt = select(Customer.customer_id, Customer.customer_name).order_by(Customer.customer_name)
    if exclude_customer_id is not None:
        stmt = stmt.where(Customer.customer_id != exclude_customer_id)
    return [tuple(row) for row in session.execute(stmt).all()]


STORE_KEY_RANGE_START = 6000
STORE_KEY_RANGE_END = 8000  # exclusive - the range is exhausted once this is hit


def next_store_key(session: Session) -> int | None:
    """Next store_key for a newly created customer: one past the current
    max, or STORE_KEY_RANGE_START if none are assigned yet. Existing
    store_key values are historical data carried over from the prior
    system rather than a live sequence, so only values already inside our
    6000-7999 range count toward that max - legacy values outside it (e.g.
    from before this feature existed) are ignored. Returns None once the
    range is exhausted, leaving store_key unset rather than overflowing
    into legacy key territory."""
    current_max = session.scalar(
        select(func.max(Customer.store_key)).where(
            Customer.store_key >= STORE_KEY_RANGE_START,
            Customer.store_key < STORE_KEY_RANGE_END,
        )
    )
    candidate = STORE_KEY_RANGE_START if current_max is None else current_max + 1
    return candidate if candidate < STORE_KEY_RANGE_END else None


def create_customer(session: Session, **fields) -> Customer:
    fields.setdefault("store_key", next_store_key(session))
    customer = Customer(**fields)
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


def update_customer(session: Session, customer_id: int, **fields) -> Customer | None:
    customer = session.get(Customer, customer_id)
    if customer is None:
        return None
    for key, value in fields.items():
        setattr(customer, key, value)
    session.commit()
    session.refresh(customer)
    return customer


def get_customer(session: Session, customer_id: int) -> Customer | None:
    stmt = (
        select(Customer)
        .options(
            joinedload(Customer.customer_type),
            joinedload(Customer.default_order_type),
            joinedload(Customer.parent),
            joinedload(Customer.children),
            joinedload(Customer.contacts),
        )
        .where(Customer.customer_id == customer_id)
    )
    return session.scalars(stmt).unique().first()


def list_contacts(session: Session, customer_id: int) -> list[CustomerContact]:
    stmt = (
        select(CustomerContact)
        .where(CustomerContact.customer_id == customer_id)
        .order_by(CustomerContact.contact_name)
    )
    return list(session.scalars(stmt).all())
