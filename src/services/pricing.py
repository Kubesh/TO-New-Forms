"""Per-case pricing.

A price is set for an item at one of three scopes (see ItemPrice): a customer,
a customer type, or the default. For a given customer, the first of these that
has a price wins:

  1. the customer's own price            ("customer")
  2. their parent account's own price    ("parent")   - a chain's negotiated
                                                         price covers its stores
  3. the price for their customer type   ("type")
  4. the default price                   ("default")

An item with none of those has no price (None) - it's left unpriced rather
than guessed at. The price a PO line was entered at is saved on the line
(unit_price / price_source), so changing a price later doesn't rewrite old POs.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.models import CustomerType, Customer, Item, ItemPrice

CENT = Decimal("0.01")
PRICE_PLACES = Decimal("0.0001")

SOURCE_LABELS = {
    "customer": "Customer price",
    "parent": "Parent account's price",
    "type": "Customer type price",
    "default": "Default price",
}


def resolve_prices(
    session: Session, customer_id: int | None, item_ids
) -> dict[int, tuple[Decimal, str]]:
    """item_id -> (per-case price, source) for each item that has a price for
    this customer; items with none are left out. customer_id None (a PO not
    linked to a customer) can only get default prices."""
    item_ids = list(set(item_ids))
    if not item_ids:
        return {}
    customer = session.get(Customer, customer_id) if customer_id else None
    own_id = customer.customer_id if customer else None
    parent_id = customer.parent_id if customer else None
    type_id = customer.customer_type_id if customer else None

    scopes = [and_(ItemPrice.customer_id.is_(None), ItemPrice.customer_type_id.is_(None))]
    customer_ids = [i for i in (own_id, parent_id) if i]
    if customer_ids:
        scopes.append(ItemPrice.customer_id.in_(customer_ids))
    if type_id:
        scopes.append(ItemPrice.customer_type_id == type_id)

    found: dict[int, dict[str, Decimal]] = {}
    rows = session.execute(
        select(ItemPrice.item_id, ItemPrice.customer_id, ItemPrice.customer_type_id, ItemPrice.price).where(
            ItemPrice.item_id.in_(item_ids), or_(*scopes)
        )
    )
    for item_id, price_customer_id, price_type_id, price in rows:
        if price_customer_id is not None:
            scope = "customer" if price_customer_id == own_id else "parent"
        elif price_type_id is not None:
            scope = "type"
        else:
            scope = "default"
        found.setdefault(item_id, {})[scope] = price

    resolved = {}
    for item_id, by_scope in found.items():
        for scope in ("customer", "parent", "type", "default"):
            if scope in by_scope:
                resolved[item_id] = (by_scope[scope], scope)
                break
    return resolved


def resolve_price(
    session: Session, customer_id: int | None, item_id: int
) -> tuple[Decimal | None, str | None]:
    return resolve_prices(session, customer_id, [item_id]).get(item_id, (None, None))


def _scope_filter(customer_type_id: int | None, customer_id: int | None):
    if customer_type_id is not None and customer_id is not None:
        raise ValueError("A price is for a customer or a customer type, not both.")
    if customer_id is not None:
        return ItemPrice.customer_id == customer_id
    if customer_type_id is not None:
        return ItemPrice.customer_type_id == customer_type_id
    return and_(ItemPrice.customer_id.is_(None), ItemPrice.customer_type_id.is_(None))


def _apply_price(
    session: Session,
    item_id: int,
    price: Decimal | None,
    customer_type_id: int | None,
    customer_id: int | None,
) -> None:
    existing = session.scalars(
        select(ItemPrice).where(
            ItemPrice.item_id == item_id, _scope_filter(customer_type_id, customer_id)
        )
    ).first()
    if price is None:
        if existing is not None:
            session.delete(existing)
        return
    price = Decimal(price).quantize(PRICE_PLACES, ROUND_HALF_UP)
    if price < 0:
        raise ValueError("A price can't be negative.")
    if existing is not None:
        existing.price = price
    else:
        session.add(
            ItemPrice(
                item_id=item_id,
                customer_type_id=customer_type_id,
                customer_id=customer_id,
                price=price,
            )
        )


def set_price(
    session: Session,
    item_id: int,
    price: Decimal | None,
    *,
    customer_type_id: int | None = None,
    customer_id: int | None = None,
) -> None:
    """Sets (or with None, clears) one price at one scope."""
    _apply_price(session, item_id, price, customer_type_id, customer_id)
    session.commit()


def set_prices(session: Session, changes: list[dict]) -> None:
    """Applies many changes in one commit. Each change is a dict with item_id,
    price, and optionally customer_type_id or customer_id."""
    for change in changes:
        _apply_price(
            session,
            change["item_id"],
            change["price"],
            change.get("customer_type_id"),
            change.get("customer_id"),
        )
    session.commit()


def price_grid(session: Session):
    """(sellable items, customer types, {(item_id, customer_type_id or None):
    price}) for the Pricing page; None as the type is the default price."""
    items = list(session.scalars(select(Item).where(Item.sellable.is_(True)).order_by(Item.sku)))
    types = list(session.scalars(select(CustomerType).order_by(CustomerType.name)))
    prices = {
        (item_id, type_id): price
        for item_id, type_id, price in session.execute(
            select(ItemPrice.item_id, ItemPrice.customer_type_id, ItemPrice.price).where(
                ItemPrice.customer_id.is_(None)
            )
        )
    }
    return items, types, prices


def customer_price_rows(session: Session, customer_id: int) -> list[dict]:
    """For a customer's Pricing section: every sellable item with the customer's
    own price (override), the price a new PO line would get now (effective), and
    where that comes from."""
    items = list(session.scalars(select(Item).where(Item.sellable.is_(True)).order_by(Item.sku)))
    effective = resolve_prices(session, customer_id, [item.item_id for item in items])
    own = {
        item_id: price
        for item_id, price in session.execute(
            select(ItemPrice.item_id, ItemPrice.price).where(ItemPrice.customer_id == customer_id)
        )
    }
    rows = []
    for item in items:
        price, source = effective.get(item.item_id, (None, None))
        rows.append(
            {
                "item_id": item.item_id,
                "sku": item.sku,
                "name": item.name,
                "override": own.get(item.item_id),
                "effective": price,
                "source": source,
            }
        )
    return rows


def line_amount(unit_price: Decimal | None, quantity) -> Decimal | None:
    """A line's amount, rounded to the cent; None if the line has no price."""
    if unit_price is None:
        return None
    return (Decimal(unit_price) * Decimal(quantity)).quantize(CENT, ROUND_HALF_UP)


def order_total(lines) -> tuple[Decimal, int]:
    """(total of the priced lines, number of lines with a quantity but no
    price). The total is the sum of the cent-rounded line amounts, as an
    invoice adds them."""
    total = Decimal(0)
    unpriced = 0
    for line in lines:
        if line.quantity <= 0:
            continue
        amount = line_amount(line.unit_price, line.quantity)
        if amount is None:
            unpriced += 1
        else:
            total += amount
    return total, unpriced
