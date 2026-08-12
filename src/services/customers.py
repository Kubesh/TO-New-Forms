from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from src.models import Customer, CustomerContact, CustomerType


def list_customer_types(session: Session) -> list[CustomerType]:
    stmt = select(CustomerType).order_by(CustomerType.name)
    return list(session.scalars(stmt).all())


def get_duplicate_customer_names(session: Session) -> set[str]:
    """Customer names that appear on more than one customer record."""
    stmt = (
        select(Customer.customer_name)
        .group_by(Customer.customer_name)
        .having(func.count() > 1)
    )
    return set(session.scalars(stmt).all())


def search_customers(session: Session, query: str | None = None) -> list[Customer]:
    stmt = select(Customer).options(
        joinedload(Customer.customer_type),
        joinedload(Customer.parent),
    )
    if query:
        stmt = stmt.where(Customer.customer_name.ilike(f"%{query}%"))
    stmt = stmt.order_by(Customer.customer_name)
    return list(session.scalars(stmt).unique().all())


def list_customer_choices(
    session: Session, exclude_customer_id: int | None = None
) -> list[tuple[int, str]]:
    """(customer_id, customer_name) pairs, for populating parent-account pickers."""
    stmt = select(Customer.customer_id, Customer.customer_name).order_by(Customer.customer_name)
    if exclude_customer_id is not None:
        stmt = stmt.where(Customer.customer_id != exclude_customer_id)
    return [tuple(row) for row in session.execute(stmt).all()]


def create_customer(session: Session, **fields) -> Customer:
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
