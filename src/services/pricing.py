"""Per-case pricing.

A price is set for a target - one item (a SKU), or a category (a line or a form
factor: every item under it) - at one of three scopes (see ItemPrice): a
customer, a customer type, or the default.

For a given customer the scopes are tried in this order, and the first one that
has a price for the item wins:

  1. the customer's own prices            ("customer")
  2. their parent account's own prices    ("parent")   - a chain's negotiated
                                                         price covers its stores
  3. the prices for their customer type   ("type")
  4. the default prices                   ("default")

Within one scope, a price on the item's SKU wins over a price on its category,
and the nearest category wins (form factor, then its line, then the top-level
category). An item with no price anywhere is left unpriced (None) rather than
guessed at. The price a PO line was entered at is saved on the line
(unit_price / price_source), so changing a price later doesn't rewrite old POs.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.models import Category, Customer, Item, ItemPrice
from src.services.categories import SELLABLE_CATEGORY_NAME

CENT = Decimal("0.01")
PRICE_PLACES = Decimal("0.0001")

SOURCE_LABELS = {
    "customer": "Customer price",
    "parent": "Parent account's price",
    "type": "Customer type price",
    "default": "Default price",
}

# A scope is (label, customer_id, customer_type_id) - the label is one of the
# SOURCE_LABELS keys, the ids pick out which ItemPrice rows belong to it.
Scope = tuple[str, int | None, int | None]
DEFAULT_SCOPE: Scope = ("default", None, None)


def customer_scopes(session: Session, customer_id: int | None) -> list[Scope]:
    """The scopes that apply to a customer, highest priority first. A PO not
    linked to a customer (None) can only get default prices."""
    customer = session.get(Customer, customer_id) if customer_id else None
    if customer is None:
        return [DEFAULT_SCOPE]
    scopes: list[Scope] = [("customer", customer.customer_id, None)]
    if customer.parent_id:
        scopes.append(("parent", customer.parent_id, None))
    if customer.customer_type_id:
        scopes.append(("type", None, customer.customer_type_id))
    scopes.append(DEFAULT_SCOPE)
    return scopes


def view_scopes(
    session: Session, customer_type_id: int | None = None, customer_id: int | None = None
) -> list[Scope]:
    """The scopes behind a pricing editor: a customer sees everything that
    applies to them, a customer type sees its own prices over the default's,
    and the default sees only itself."""
    if customer_id is not None:
        return customer_scopes(session, customer_id)
    if customer_type_id is not None:
        return [("type", None, customer_type_id), DEFAULT_SCOPE]
    return [DEFAULT_SCOPE]


def _own_scope(customer_type_id: int | None, customer_id: int | None) -> Scope:
    if customer_type_id is not None and customer_id is not None:
        raise ValueError("A price is for a customer or a customer type, not both.")
    if customer_id is not None:
        return ("customer", customer_id, None)
    if customer_type_id is not None:
        return ("type", None, customer_type_id)
    return DEFAULT_SCOPE


def _category_maps(session: Session):
    rows = session.execute(select(Category.category_id, Category.name, Category.parent_id)).all()
    names = {category_id: name for category_id, name, _ in rows}
    parents = {category_id: parent_id for category_id, _, parent_id in rows}
    return names, parents


def _sellable_category_ids(names: dict, parents: dict) -> set[int]:
    """Every category under the Sellable Product category (not itself)."""
    roots = {c for c, n in names.items() if n == SELLABLE_CATEGORY_NAME and parents[c] is None}
    return {c for c in names if c not in roots and set(_chain(parents, c)) & roots}


def _chain(parents: dict, category_id: int | None) -> list[int]:
    """category_id and its ancestors, nearest first."""
    chain = []
    while category_id is not None and category_id not in chain:
        chain.append(category_id)
        category_id = parents.get(category_id)
    return chain


def _target_label(names: dict, parents: dict, category_id: int) -> str:
    """A category target for display: its path below the top-level category
    ("Drinking Chocolate › SUP"), or just its own name if it is top-level."""
    path = [names[c] for c in reversed(_chain(parents, category_id))]
    return " › ".join(path[1:] or path)


def _price_lookup(session: Session, scopes: list[Scope], item_ids, category_ids) -> dict:
    """{(item_id, category_id, customer_id, customer_type_id): price} for the
    given targets in the given scopes."""
    item_ids, category_ids = list(item_ids), list(category_ids)
    targets = []
    if item_ids:
        targets.append(ItemPrice.item_id.in_(item_ids))
    if category_ids:
        targets.append(ItemPrice.category_id.in_(category_ids))
    if not targets:
        return {}
    in_scope = or_(
        *[
            (ItemPrice.customer_id == customer_id if customer_id is not None else ItemPrice.customer_id.is_(None))
            & (
                ItemPrice.customer_type_id == type_id
                if type_id is not None
                else ItemPrice.customer_type_id.is_(None)
            )
            for _, customer_id, type_id in scopes
        ]
    )
    rows = session.execute(
        select(
            ItemPrice.item_id,
            ItemPrice.category_id,
            ItemPrice.customer_id,
            ItemPrice.customer_type_id,
            ItemPrice.price,
        ).where(or_(*targets), in_scope)
    )
    return {(i, c, cu, ty): price for i, c, cu, ty, price in rows}


def resolve_items(session: Session, scopes: list[Scope], item_ids) -> dict:
    """item_id -> (price, scope label, target) for each item that has a price
    in these scopes; items with none are left out. target is "SKU" when the
    price is on the item itself, else the category it is on."""
    item_ids = list(set(item_ids))
    if not item_ids:
        return {}
    names, parents = _category_maps(session)
    category_of = dict(
        session.execute(select(Item.item_id, Item.category_id).where(Item.item_id.in_(item_ids))).all()
    )
    chains = {item_id: _chain(parents, category_of.get(item_id)) for item_id in item_ids}
    category_ids = {c for chain in chains.values() for c in chain}
    prices = _price_lookup(session, scopes, item_ids, category_ids)

    resolved = {}
    for item_id in item_ids:
        for label, customer_id, type_id in scopes:
            found = prices.get((item_id, None, customer_id, type_id))
            target = "SKU"
            if found is None:
                for category_id in chains[item_id]:
                    found = prices.get((None, category_id, customer_id, type_id))
                    if found is not None:
                        target = _target_label(names, parents, category_id)
                        break
            if found is not None:
                resolved[item_id] = (found, label, target)
                break
    return resolved


def resolve_category(session: Session, scopes: list[Scope], category_id: int):
    """(price, scope label, target) for a category in these scopes - the price
    its items get when they have no SKU price of their own - or None."""
    names, parents = _category_maps(session)
    chain = _chain(parents, category_id)
    prices = _price_lookup(session, scopes, [], chain)
    for label, customer_id, type_id in scopes:
        for chain_id in chain:
            found = prices.get((None, chain_id, customer_id, type_id))
            if found is not None:
                return found, label, _target_label(names, parents, chain_id)
    return None


def resolve_prices(
    session: Session, customer_id: int | None, item_ids
) -> dict[int, tuple[Decimal, str]]:
    """item_id -> (per-case price, scope label) for each item that has a price
    for this customer; items with none are left out."""
    detailed = resolve_items(session, customer_scopes(session, customer_id), item_ids)
    return {item_id: (price, scope) for item_id, (price, scope, _) in detailed.items()}


def resolve_price(
    session: Session, customer_id: int | None, item_id: int
) -> tuple[Decimal | None, str | None]:
    return resolve_prices(session, customer_id, [item_id]).get(item_id, (None, None))


def describe_source(scope: str | None, target: str | None) -> str:
    if scope is None:
        return "No price"
    label = SOURCE_LABELS.get(scope, scope)
    return f"{label} ({target})" if target else label


def _apply_price(
    session: Session,
    price: Decimal | None,
    item_id: int | None,
    category_id: int | None,
    customer_type_id: int | None,
    customer_id: int | None,
) -> None:
    if (item_id is None) == (category_id is None):
        raise ValueError("A price is for an item or a category.")
    _, scope_customer_id, scope_type_id = _own_scope(customer_type_id, customer_id)

    def match(column, value):
        return column == value if value is not None else column.is_(None)

    existing = session.scalars(
        select(ItemPrice).where(
            match(ItemPrice.item_id, item_id),
            match(ItemPrice.category_id, category_id),
            match(ItemPrice.customer_id, scope_customer_id),
            match(ItemPrice.customer_type_id, scope_type_id),
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
        existing.updated_at = func.now()
    else:
        session.add(
            ItemPrice(
                item_id=item_id,
                category_id=category_id,
                customer_type_id=scope_type_id,
                customer_id=scope_customer_id,
                price=price,
            )
        )


def set_price(
    session: Session,
    price: Decimal | None,
    *,
    item_id: int | None = None,
    category_id: int | None = None,
    customer_type_id: int | None = None,
    customer_id: int | None = None,
) -> None:
    """Sets (or with None, clears) one price: for an item or a category, at
    a customer's, a customer type's, or (neither given) the default scope."""
    _apply_price(session, price, item_id, category_id, customer_type_id, customer_id)
    session.commit()


def set_prices(session: Session, changes: list[dict]) -> None:
    """Applies many changes in one commit. Each change is a dict with price,
    item_id or category_id, and optionally customer_type_id or customer_id."""
    for change in changes:
        _apply_price(
            session,
            change["price"],
            change.get("item_id"),
            change.get("category_id"),
            change.get("customer_type_id"),
            change.get("customer_id"),
        )
    session.commit()


def line_price_rows(
    session: Session, *, customer_type_id: int | None = None, customer_id: int | None = None
) -> list[dict]:
    """For the Line tab: one row per bottom-level category under Sellable
    Product (a form factor, or a line that has none) with the price set here
    for it (own), the price it ends up with in this view (effective), where
    that comes from, and how many items it covers."""
    scopes = view_scopes(session, customer_type_id, customer_id)
    own_scope = _own_scope(customer_type_id, customer_id)
    names, parents = _category_maps(session)
    has_children = {p for p in parents.values() if p is not None}
    leaves = [c for c in _sellable_category_ids(names, parents) if c not in has_children]
    own_prices = _price_lookup(session, [own_scope], [], leaves)

    counts: dict[int, int] = {}
    for (category_id,) in session.execute(select(Item.category_id).where(Item.category_id.isnot(None))):
        for chain_id in _chain(parents, category_id):
            counts[chain_id] = counts.get(chain_id, 0) + 1

    rows = []
    for category_id in leaves:
        path = [names[c] for c in reversed(_chain(parents, category_id))]
        effective = resolve_category(session, scopes, category_id)
        rows.append(
            {
                "category_id": category_id,
                "path": path,
                "items": counts.get(category_id, 0),
                "own": own_prices.get((None, category_id, own_scope[1], own_scope[2])),
                "effective": effective[0] if effective else None,
                "source": describe_source(effective[1], effective[2]) if effective else "No price",
            }
        )
    rows.sort(key=lambda r: [p.lower() for p in r["path"]])
    return rows


def sku_price_rows(
    session: Session, *, customer_type_id: int | None = None, customer_id: int | None = None
) -> list[dict]:
    """For the SKU tab: every sellable item (marked sellable, or in the
    Sellable Product category) with the price set on the SKU here
    (own - an override of its line / form factor price), the price it ends up
    with in this view (effective), and where that comes from."""
    scopes = view_scopes(session, customer_type_id, customer_id)
    own_scope = _own_scope(customer_type_id, customer_id)
    names, parents = _category_maps(session)
    in_sellable = _sellable_category_ids(names, parents)
    items = list(
        session.scalars(
            select(Item)
            .where(Item.sellable.is_(True) | Item.category_id.in_(in_sellable or [0]))
            .order_by(Item.sku)
        )
    )
    item_ids = [item.item_id for item in items]
    effective = resolve_items(session, scopes, item_ids)
    own_prices = _price_lookup(session, [own_scope], item_ids, [])
    rows = []
    for item in items:
        found = effective.get(item.item_id)
        path = [names[c] for c in reversed(_chain(parents, item.category_id))]
        rows.append(
            {
                "item_id": item.item_id,
                "sku": item.sku,
                "name": item.name,
                "category": " › ".join(path[1:] or path),
                "own": own_prices.get((item.item_id, None, own_scope[1], own_scope[2])),
                "effective": found[0] if found else None,
                "source": describe_source(found[1], found[2]) if found else "No price",
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
