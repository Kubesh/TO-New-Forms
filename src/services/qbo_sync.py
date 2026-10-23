"""The app <-> QuickBooks Online mapping, and creating invoices from POs.

Customers: an invoice is billed to the QuickBooks customer linked to the PO's
*billing* customer - the PO customer's parent account if it has one, else the
customer itself - and shipped to the PO customer's own shipping address. So
a chain's QuickBooks customer is linked once, on the parent, and its stores
inherit it.

Items: each sellable SKU is linked to one QuickBooks product/service. Prices
are NOT taken from QuickBooks - the invoice carries the price the PO line was
entered at (unit_price).

Links belong to one QuickBooks company (realm), so sandbox and real links can
coexist; everything here works in the currently connected company.

Invoices are created unsent (no email, no status change) for someone to review
and send from QuickBooks. Faire orders never go to QuickBooks. An invoice is
refused until the customer and every SKU on the PO are linked and every line
has a price.
"""
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.models import (
    Customer,
    Item,
    PurchaseOrder,
    QboCustomerLink,
    QboInvoice,
    QboItemLink,
)
from src.services import quickbooks as qb
from src.services.app_settings import get_setting, set_setting
from src.services.customers import format_phone_number, format_postal_code, normalize_emails
from src.services.order_types import is_faire_order
from src.services.pricing import line_amount, resolve_prices
from src.services.purchase_orders import get_purchase_order, price_unpriced_lines

SEARCH_LIMIT = 25
# Invoices get their number from the app (QuickBooks' own numbering is off),
# as <prefix><next number from qbo_invoice_number_seq>. The prefix is set in the
# app (app_settings); QBO_INVOICE_PREFIX is only the default before it is.
INVOICE_PREFIX_KEY = "qbo_invoice_prefix"
DEFAULT_INVOICE_PREFIX = os.environ.get("QBO_INVOICE_PREFIX", "O-")
INVOICE_PREFIX_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,10}")


class InvoiceBlocked(Exception):
    """The invoice can't be created yet; .reasons says why."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class MissingBillEmail(InvoiceBlocked):
    """Neither the customer nor its parent account has a bill-to email. The
    caller may retry with send_without_email=True once the person agrees."""


def current_realm(session: Session) -> str | None:
    connection = qb.get_connection(session)
    return connection.realm_id if connection else None


def _normalize(name: str | None) -> str:
    return " ".join((name or "").lower().split())


# --- customers --------------------------------------------------------------


def invoice_target(
    session: Session, customer: Customer
) -> tuple[Customer, QboCustomerLink | None]:
    """The customer whose QuickBooks link an invoice for this customer uses,
    and that link (None if unlinked): the customer's own link if it has one,
    else its parent account's. A store only needs its own link when it has its
    own QuickBooks customer (a sub-customer)."""
    own = get_customer_link(session, customer.customer_id)
    if own is not None or customer.parent is None:
        return customer, own
    return customer.parent, get_customer_link(session, customer.parent.customer_id)


def get_customer_link(session: Session, customer_id: int) -> QboCustomerLink | None:
    realm = current_realm(session)
    if realm is None:
        return None
    return session.scalars(
        select(QboCustomerLink).where(
            QboCustomerLink.customer_id == customer_id, QboCustomerLink.realm_id == realm
        )
    ).first()


def customer_links_by_id(session: Session) -> dict[int, QboCustomerLink]:
    realm = current_realm(session)
    if realm is None:
        return {}
    return {
        link.customer_id: link
        for link in session.scalars(
            select(QboCustomerLink).where(QboCustomerLink.realm_id == realm)
        )
    }


def link_customer(
    session: Session, customer_id: int, qbo_customer_id: str, display_name: str | None
) -> QboCustomerLink:
    realm = current_realm(session)
    if realm is None:
        raise qb.QuickBooksNotConnected("QuickBooks isn't connected yet.")
    taken = session.scalars(
        select(QboCustomerLink).where(
            QboCustomerLink.realm_id == realm,
            QboCustomerLink.qbo_customer_id == qbo_customer_id,
            QboCustomerLink.customer_id != customer_id,
        )
    ).first()
    if taken is not None:
        other = session.get(Customer, taken.customer_id)
        raise ValueError(
            f"That QuickBooks customer is already linked to {other.customer_name if other else 'another customer'}."
        )
    link = get_customer_link(session, customer_id)
    if link is None:
        link = QboCustomerLink(customer_id=customer_id, realm_id=realm)
        session.add(link)
    link.qbo_customer_id = qbo_customer_id
    link.qbo_display_name = display_name
    session.commit()
    return link


def unlink_customer(session: Session, customer_id: int) -> None:
    link = get_customer_link(session, customer_id)
    if link is not None:
        session.delete(link)
        session.commit()


def search_qbo_customers(session: Session, text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    return qb.query(
        session,
        "select * from Customer where Active = true and DisplayName like "
        f"'%{qb.escape_literal(text)}%'",
        page_size=SEARCH_LIMIT,
    )[:SEARCH_LIMIT]


def _address(prefix: str, customer: Customer) -> dict | None:
    lines = [
        getattr(customer, f"{prefix}_address_line1"),
        getattr(customer, f"{prefix}_address_line2"),
    ]
    address = {
        "City": getattr(customer, f"{prefix}_city"),
        "CountrySubDivisionCode": getattr(customer, f"{prefix}_state"),
        "PostalCode": getattr(customer, f"{prefix}_postal_code"),
        "Country": getattr(customer, f"{prefix}_country"),
    }
    for number, line in enumerate([l for l in lines if l], start=1):
        address[f"Line{number}"] = line
    address = {key: value for key, value in address.items() if value}
    return address or None


def create_qbo_customer(session: Session, customer: Customer) -> dict:
    """Creates a QuickBooks customer from an app customer and links them."""
    payload: dict = {"DisplayName": customer.customer_name, "CompanyName": customer.customer_name}
    bill = _address("billing", customer)
    if bill:
        payload["BillAddr"] = bill
    ship = _address("shipping", customer)
    if ship:
        payload["ShipAddr"] = ship
    if customer.phone_number:
        payload["PrimaryPhone"] = {"FreeFormNumber": customer.phone_number}
    data = qb._request(session, "POST", "customer", json=payload)
    created = data["Customer"]
    link_customer(session, customer.customer_id, str(created["Id"]), created.get("DisplayName"))
    return created


def billing_customers(session: Session, include_archived: bool = False) -> list[Customer]:
    """Top-level accounts: the ones auto-matched by name and counted on the QuickBooks
    page. Stores of a parent account can be linked individually from their own page."""
    stmt = select(Customer).where(Customer.parent_id.is_(None)).order_by(Customer.customer_name)
    if not include_archived:
        stmt = stmt.where(Customer.archived.is_(False))
    return list(session.scalars(stmt))


# QuickBooks address part -> the app's customer field suffix.
_ADDRESS_PARTS = (
    ("Line1", "address_line1"),
    ("Line2", "address_line2"),
    ("City", "city"),
    ("CountrySubDivisionCode", "state"),
    ("PostalCode", "postal_code"),
    ("Country", "country"),
)
_ADDRESS_SOURCES = (("billing", "BillAddr"), ("shipping", "ShipAddr"))


def _fit(field: str, value: str | None) -> str | None:
    """The value trimmed to the customer column's length, or None if blank."""
    value = (value or "").strip()
    if not value:
        return None
    return value[: Customer.__table__.columns[field].type.length]


def plan_customer_sync(session: Session) -> list[dict]:
    """What syncing from QuickBooks would fill in: for each linked, active
    customer, the fields that are blank in the app and have a value in
    QuickBooks. Nothing the app already has is ever replaced, and an address
    is only copied when the app's whole address (billing or shipping) is
    empty, so a half-filled address never ends up mixed with QuickBooks'.
    Each entry: {customer_id, name, qbo_name, fields: {field: value}}."""
    links = customer_links_by_id(session)
    if not links:
        return []
    qbo_by_id = {str(c["Id"]): c for c in qb.list_customers(session)}
    customers = session.scalars(
        select(Customer)
        .where(Customer.customer_id.in_(list(links)), Customer.archived.is_(False))
        .order_by(Customer.customer_name)
    )
    plan = []
    for customer in customers:
        link = links[customer.customer_id]
        qbo = qbo_by_id.get(link.qbo_customer_id)
        if qbo is None:
            continue
        fields: dict[str, str] = {}
        if not (customer.bill_to_email or "").strip():
            email, error = normalize_emails((qbo.get("PrimaryEmailAddr") or {}).get("Address"))
            if email and not error:
                fields["bill_to_email"] = _fit("bill_to_email", email)
        if not (customer.phone_number or "").strip():
            phone, error = format_phone_number((qbo.get("PrimaryPhone") or {}).get("FreeFormNumber") or "")
            if phone and not error:
                fields["phone_number"] = _fit("phone_number", phone)
        for prefix, key in _ADDRESS_SOURCES:
            current = [getattr(customer, f"{prefix}_{part}") for _, part in _ADDRESS_PARTS]
            if any((value or "").strip() for value in current):
                continue
            address = qbo.get(key) or {}
            for qbo_part, part in _ADDRESS_PARTS:
                value = address.get(qbo_part)
                if part == "postal_code" and value:
                    value = format_postal_code(value)
                value = _fit(f"{prefix}_{part}", value)
                if value:
                    fields[f"{prefix}_{part}"] = value
        fields = {k: v for k, v in fields.items() if v}
        if fields:
            plan.append(
                {
                    "customer_id": customer.customer_id,
                    "name": customer.customer_name,
                    "qbo_name": link.qbo_display_name or link.qbo_customer_id,
                    "fields": fields,
                }
            )
    return plan


def apply_customer_sync(session: Session, plan: list[dict]) -> int:
    """Writes a plan from plan_customer_sync, skipping any field that has been
    filled in since the plan was made. Returns the number of customers changed."""
    changed = 0
    for entry in plan:
        customer = session.get(Customer, entry["customer_id"])
        if customer is None:
            continue
        touched = False
        for field_name, value in entry["fields"].items():
            if not (getattr(customer, field_name) or "").strip():
                setattr(customer, field_name, value)
                touched = True
        changed += touched
    session.commit()
    return changed


def plan_customer_matches(session: Session) -> tuple[list[tuple[Customer, dict]], int]:
    """Unlinked billing customers whose name exactly matches (ignoring case
    and spacing) exactly one QuickBooks customer not already linked: a list of
    (customer, qbo customer) and the number of unlinked customers left."""
    linked = customer_links_by_id(session)
    taken = {link.qbo_customer_id for link in linked.values()}
    by_name: dict[str, list[dict]] = {}
    for qbo_customer in qb.list_customers(session):
        by_name.setdefault(_normalize(qbo_customer.get("DisplayName")), []).append(qbo_customer)
    matches, unmatched = [], 0
    for customer in billing_customers(session):
        if customer.customer_id in linked:
            continue
        candidates = [
            c for c in by_name.get(_normalize(customer.customer_name), []) if str(c["Id"]) not in taken
        ]
        if len(candidates) == 1:
            matches.append((customer, candidates[0]))
            taken.add(str(candidates[0]["Id"]))
        else:
            unmatched += 1
    return matches, unmatched


# --- items ------------------------------------------------------------------

ITEM_TYPES = "('Service', 'Inventory', 'NonInventory')"


def current_item_links(session: Session) -> dict[int, QboItemLink]:
    realm = current_realm(session)
    if realm is None:
        return {}
    return {
        link.item_id: link
        for link in session.scalars(select(QboItemLink).where(QboItemLink.realm_id == realm))
    }


def link_item(
    session: Session, item_id: int, qbo_item_id: str, name: str | None
) -> QboItemLink:
    realm = current_realm(session)
    if realm is None:
        raise qb.QuickBooksNotConnected("QuickBooks isn't connected yet.")
    taken = session.scalars(
        select(QboItemLink).where(
            QboItemLink.realm_id == realm,
            QboItemLink.qbo_item_id == qbo_item_id,
            QboItemLink.item_id != item_id,
        )
    ).first()
    if taken is not None:
        other = session.get(Item, taken.item_id)
        raise ValueError(
            f"That QuickBooks item is already linked to {other.sku if other else 'another SKU'}."
        )
    link = current_item_links(session).get(item_id)
    if link is None:
        link = QboItemLink(item_id=item_id, realm_id=realm)
        session.add(link)
    link.qbo_item_id = qbo_item_id
    link.qbo_item_name = name
    session.commit()
    return link


def unlink_item(session: Session, item_id: int) -> None:
    link = current_item_links(session).get(item_id)
    if link is not None:
        session.delete(link)
        session.commit()


def search_qbo_items(session: Session, text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    return qb.query(
        session,
        f"select * from Item where Active = true and Type in {ITEM_TYPES} and "
        f"Name like '%{qb.escape_literal(text)}%'",
        page_size=SEARCH_LIMIT,
    )[:SEARCH_LIMIT]


def sellable_items(session: Session) -> list[Item]:
    return list(session.scalars(select(Item).where(Item.sellable.is_(True)).order_by(Item.sku)))


def plan_item_matches(session: Session) -> tuple[list[tuple[Item, dict]], int]:
    """Unlinked sellable items matched to a QuickBooks item by its SKU field,
    else by an exact name, when that picks exactly one item not already
    linked: (item, qbo item) pairs, and how many unlinked items are left."""
    linked = current_item_links(session)
    taken = {link.qbo_item_id for link in linked.values()}
    qbo_items = qb.query(
        session, f"select * from Item where Active = true and Type in {ITEM_TYPES}"
    )
    by_sku: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for qbo_item in qbo_items:
        if qbo_item.get("Sku"):
            by_sku.setdefault(_normalize(qbo_item["Sku"]), []).append(qbo_item)
        by_name.setdefault(_normalize(qbo_item.get("Name")), []).append(qbo_item)
    matches, unmatched = [], 0
    for item in sellable_items(session):
        if item.item_id in linked:
            continue
        for pool, key in ((by_sku, item.sku), (by_name, item.name)):
            candidates = [c for c in pool.get(_normalize(key), []) if str(c["Id"]) not in taken]
            if len(candidates) == 1:
                matches.append((item, candidates[0]))
                taken.add(str(candidates[0]["Id"]))
                break
        else:
            unmatched += 1
    return matches, unmatched


# --- invoices ---------------------------------------------------------------


@dataclass
class InvoiceCheck:
    excluded: str | None = None  # why this order never goes to QuickBooks
    blockers: list[str] = field(default_factory=list)
    # Things worth confirming but not blocking (e.g. no bill-to email).
    warnings: list[str] = field(default_factory=list)
    invoice: QboInvoice | None = None  # the PO's live invoice, if it has one

    @property
    def can_create(self) -> bool:
        return not self.excluded and not self.blockers and self.invoice is None


def get_live_invoice(session: Session, po_id: int) -> QboInvoice | None:
    realm = current_realm(session)
    if realm is None:
        return None
    return session.scalars(
        select(QboInvoice).where(
            QboInvoice.po_id == po_id,
            QboInvoice.realm_id == realm,
            QboInvoice.status == "created",
        )
    ).first()


def list_invoice_attempts(session: Session, po_id: int) -> list[QboInvoice]:
    return list(
        session.scalars(
            select(QboInvoice)
            .where(QboInvoice.po_id == po_id)
            .order_by(QboInvoice.created_at.desc(), QboInvoice.qbo_invoice_record_id.desc())
        )
    )


def _live_lines(po: PurchaseOrder):
    return [line for line in po.line_items if line.quantity and line.quantity > 0]


def check_invoice(session: Session, po: PurchaseOrder) -> InvoiceCheck:
    check = InvoiceCheck()
    if is_faire_order(po.order_type):
        check.excluded = "Faire orders aren't invoiced in QuickBooks."
        return check
    check.invoice = get_live_invoice(session, po.po_id)
    if check.invoice is not None:
        return check

    if po.voided:
        check.blockers.append("This PO is voided.")
    realm = current_realm(session)
    if realm is None:
        check.blockers.append("QuickBooks isn't connected - run python scripts/qbo_connect.py.")
    if po.customer is None:
        check.blockers.append("The PO has no customer.")
    else:
        target, target_link = invoice_target(session, po.customer)
        if realm and target_link is None:
            check.blockers.append(f"{target.customer_name} isn't linked to a QuickBooks customer.")
        if resolve_bill_email(po.customer) is None:
            check.warnings.append(missing_email_message(po.customer))
    lines = _live_lines(po)
    if not lines:
        check.blockers.append("The PO has no lines with a quantity.")
    if realm:
        links = current_item_links(session)
        missing = [l.sku or "?" for l in lines if l.item_id is None or l.item_id not in links]
        if missing:
            check.blockers.append(f"Not linked to a QuickBooks item: {', '.join(missing)}.")
    # A line left unpriced earlier counts as priced if the customer's pricing
    # now covers it (create_invoice fills those in before invoicing).
    could_price = resolve_prices(
        session, po.customer_id, [l.item_id for l in lines if l.unit_price is None and l.item_id]
    )
    unpriced = [
        l.sku or "?" for l in lines if l.unit_price is None and l.item_id not in could_price
    ]
    if unpriced:
        check.blockers.append(
            f"No price set for: {', '.join(unpriced)}. Set the pricing for this customer "
            "or their customer type first."
        )
    return check


def get_invoice_prefix(session: Session) -> str:
    return get_setting(session, INVOICE_PREFIX_KEY) or DEFAULT_INVOICE_PREFIX


def _clean_invoice_prefix(prefix: str) -> str:
    prefix = (prefix or "").strip()
    if not INVOICE_PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError(
            "The prefix can be 1 to 10 letters, numbers, dashes, dots or underscores (no spaces)."
        )
    return prefix


def set_invoice_prefix(session: Session, prefix: str) -> None:
    set_setting(session, INVOICE_PREFIX_KEY, _clean_invoice_prefix(prefix))


def peek_next_invoice_number(session: Session) -> int:
    """The number the next invoice will get, without using it up."""
    last_value, is_called = session.execute(
        text("SELECT last_value, is_called FROM qbo_invoice_number_seq")
    ).one()
    return last_value + 1 if is_called else last_value


def set_next_invoice_number(session: Session, number: int) -> None:
    """Moves the counter so the next invoice gets `number`. It can only go up
    (or stay put): a lower number could repeat one already used."""
    if number < 1:
        raise ValueError("The invoice number must be 1 or more.")
    # One statement, so the check and the move can't be split by another
    # invoice taking a number in between.
    moved = session.execute(
        text(
            "SELECT setval('qbo_invoice_number_seq', CAST(:n AS bigint), false) WHERE CAST(:n AS bigint) >= "
            "(SELECT CASE WHEN is_called THEN last_value + 1 ELSE last_value END "
            "FROM qbo_invoice_number_seq)"
        ),
        {"n": number},
    ).first()
    if moved is None:
        current = peek_next_invoice_number(session)
        session.rollback()
        raise ValueError(f"The next number can't go backwards - it is already {current}.")
    session.commit()


def update_invoice_numbering(session: Session, prefix: str, number: int) -> None:
    """Sets the prefix and the next number together. Both are checked before
    either is saved, so a refused number never leaves a half-applied change."""
    prefix = _clean_invoice_prefix(prefix)
    set_next_invoice_number(session, number)  # refuses to go backwards
    set_invoice_prefix(session, prefix)


def next_invoice_number(session: Session) -> str:
    prefix = get_invoice_prefix(session)
    return f"{prefix}{session.scalar(text('SELECT nextval(\'qbo_invoice_number_seq\')'))}"


def _invoice_number_for_attempt(session: Session, po_id: int, realm: str) -> str:
    """The number for a new attempt. If this PO's last attempt was refused
    (or never got an answer) its number never made it onto an invoice, so it is
    reused instead of leaving a gap, unless QuickBooks refused it as a duplicate."""
    last = session.scalars(
        select(QboInvoice)
        .where(QboInvoice.po_id == po_id, QboInvoice.realm_id == realm)
        .order_by(QboInvoice.qbo_invoice_record_id.desc())
    ).first()
    if (
        last is not None
        and last.status in ("failed", "pending")
        and last.doc_number
        and "uplicate" not in (last.error or "")
    ):
        return last.doc_number
    return next_invoice_number(session)


PO_FIELD_MAX_LENGTH = 31  # QuickBooks custom field values are limited to 31 characters


def _custom_fields_from_preferences(session: Session) -> dict[str, str]:
    """{definition id: name} of the enabled custom fields in the sales form settings."""
    prefs = qb._request(session, "GET", "preferences").get("Preferences", {})
    groups = (prefs.get("SalesFormsPrefs") or {}).get("CustomField") or []
    names, enabled = {}, {}
    for group in groups:
        for entry in group.get("CustomField", []):
            name = entry.get("Name", "")
            if match := re.fullmatch(r"SalesFormsPrefs\.SalesCustomName(\d+)", name):
                names[match.group(1)] = entry.get("StringValue", "")
            elif match := re.fullmatch(r"SalesFormsPrefs\.UseSalesCustom(\d+)", name):
                enabled[match.group(1)] = bool(entry.get("BooleanValue"))
    return {k: v for k, v in names.items() if v and enabled.get(k, True)}


ENHANCED_CUSTOM_FIELDS = "enhancedAllCustomFields"


def _custom_fields_from_invoices(session: Session, enhanced: bool = False) -> dict[str, str]:
    """{definition id: name} read off the company's latest invoices, which list
    the custom fields defined for invoices (empty ones too). Without
    `enhanced`, QuickBooks only reports a few of them; with it, all."""
    params = {
        "query": "select * from Invoice order by MetaData.LastUpdatedTime desc "
        "STARTPOSITION 1 MAXRESULTS 10"
    }
    if enhanced:
        params["include"] = ENHANCED_CUSTOM_FIELDS
    data = qb._request(session, "GET", "query", params=params)
    found: dict[str, str] = {}
    for invoice in data.get("QueryResponse", {}).get("Invoice", []):
        for field in invoice.get("CustomField") or []:
            if field.get("DefinitionId") and field.get("Name"):
                found.setdefault(str(field["DefinitionId"]), field["Name"])
    return found


def _looks_like_po(label: str) -> bool:
    """"PO Reference no.", "PO Number", "PONumber", "P.O. #", "Customer PO",
    "Purchase Order"... but not "Posting date"."""
    lowered = label.lower()
    flat = re.sub(r"[^a-z]", "", lowered)
    return (
        bool(re.search(r"\bp\.?o\b", lowered))
        or flat.startswith(("ponumber", "poref", "pono"))
        or "purchaseorder" in flat
    )


def _first_po_field(fields: dict[str, str]) -> tuple[str, str] | None:
    for definition_id, label in sorted(fields.items()):
        if _looks_like_po(label):
            return definition_id, label
    return None


def find_po_field(session: Session) -> tuple[tuple[str, str, bool] | None, dict[str, str]]:
    """Looks for the invoice field the PO number goes in (named like "PO
    Reference no." / "PO Number"): in the sales form settings, then on recent
    invoices, then on recent invoices again asking for all the custom fields
    (QuickBooks hides some - including, on some companies, the PO one - unless
    asked). Returns ((definition id, name, needs the enhanced parameter) or
    None, every field seen). QBO_PO_CUSTOM_FIELD_ID overrides the search."""
    override = os.environ.get("QBO_PO_CUSTOM_FIELD_ID", "").strip()
    if override:
        # Ids from 1000000001 up are the "enhanced" custom fields.
        return (override, "PO Reference no.", override.isdigit() and int(override) >= 1_000_000_000), {}
    seen: dict[str, str] = {}
    try:
        seen.update(_custom_fields_from_preferences(session))
    except qb.QuickBooksError:
        pass
    seen.update({k: v for k, v in _custom_fields_from_invoices(session).items() if k not in seen})
    if found := _first_po_field(seen):
        return (*found, False), seen
    enhanced = _custom_fields_from_invoices(session, enhanced=True)
    seen.update({k: v for k, v in enhanced.items() if k not in seen})
    if found := _first_po_field(enhanced):
        return (*found, True), seen
    return None, seen


def invoice_custom_fields(session: Session) -> dict[str, str]:
    return find_po_field(session)[1]


def resolve_bill_email(customer: Customer) -> str | None:
    """The bill-to email an invoice for this customer is sent with: the
    customer's own, else its parent account's, else None."""
    for source in (customer, customer.parent):
        email = ((source.bill_to_email if source else None) or "").strip()
        if email:
            return ",".join(part.strip() for part in email.split(","))
    return None


def missing_email_message(customer: Customer) -> str:
    if customer.parent is not None:
        return (
            f"Neither {customer.customer_name} nor its parent account "
            f"{customer.parent.customer_name} has a bill-to email."
        )
    return f"{customer.customer_name} has no bill-to email."


def customer_terms(session: Session, qbo_customer_id: str) -> dict | None:
    """The payment terms set on a QuickBooks customer, as an invoice
    SalesTermRef, or None. (The API doesn't copy these onto the invoice the
    way the QuickBooks screen does.)"""
    rows = qb.query(
        session,
        f"select * from Customer where Id = '{qb.escape_literal(qbo_customer_id)}'",
        page_size=2,
    )
    ref = rows[0].get("SalesTermRef") if rows else None
    return {"value": ref["value"]} if ref and ref.get("value") else None


def _invoice_terms(session: Session, customer: Customer, qbo_customer_id: str) -> dict | None:
    """Terms for an invoice to the linked QuickBooks customer; a store linked
    to its own sub-customer with no terms of its own uses its parent's."""
    terms = customer_terms(session, qbo_customer_id)
    if terms is None and customer.parent is not None:
        parent_link = get_customer_link(session, customer.parent.customer_id)
        if parent_link is not None and parent_link.qbo_customer_id != qbo_customer_id:
            terms = customer_terms(session, parent_link.qbo_customer_id)
    return terms


def build_invoice_payload(
    po: PurchaseOrder,
    qbo_customer_id: str,
    item_links: dict[int, QboItemLink],
    po_field: tuple[str, str, bool] | None = None,
    sales_term_ref: dict | None = None,
    bill_email: str | None = None,
    doc_number: str | None = None,
) -> dict:
    lines = []
    for line in _live_lines(po):
        lines.append(
            {
                "DetailType": "SalesItemLineDetail",
                "Amount": float(line_amount(line.unit_price, line.quantity)),
                "SalesItemLineDetail": {
                    "ItemRef": {"value": item_links[line.item_id].qbo_item_id},
                    "Qty": int(line.quantity),
                    "UnitPrice": float(Decimal(line.unit_price)),
                },
            }
        )
    payload: dict = {
        "CustomerRef": {"value": qbo_customer_id},
        "TxnDate": (po.order_date or date.today()).isoformat(),
        "Line": lines,
        "PrivateNote": "Created from Treehouse Operations App",
    }
    if po_field:
        definition_id, name, _ = po_field
        payload["CustomField"] = [
            {
                "DefinitionId": definition_id,
                "Name": name,
                "Type": "StringType",
                "StringValue": po.po_number,
            }
        ]
    # The PO's due date is the internal shipping due date, so it is never sent.
    # The customer's own payment terms are, and QuickBooks works out the
    # invoice's due date from them. The bill-to email comes from the app's own
    # customer record.
    if doc_number:
        payload["DocNumber"] = doc_number
    if sales_term_ref:
        payload["SalesTermRef"] = sales_term_ref
    if bill_email:
        payload["BillEmail"] = {"Address": bill_email}
    ship_to = po.customer
    address = _address("shipping", ship_to)
    if address:
        # Line1 is the store's name so the invoice says who it ships to; the
        # street address follows.
        street = [address.pop(key) for key in ("Line1", "Line2") if key in address]
        address["Line1"] = ship_to.customer_name
        for number, text in enumerate(street, start=2):
            address[f"Line{number}"] = text
        payload["ShipAddr"] = address
    return payload


def invoice_total(po: PurchaseOrder) -> Decimal:
    return sum(
        (line_amount(l.unit_price, l.quantity) or Decimal(0) for l in _live_lines(po)), Decimal(0)
    )


def create_invoice(
    session: Session, po_id: int, send_without_email: bool = False
) -> QboInvoice:
    """Creates the PO's invoice in QuickBooks (unsent). Raises InvoiceBlocked
    if it can't be created yet, QuickBooksError if QuickBooks refuses."""
    po = get_purchase_order(session, po_id)
    if po is None:
        raise InvoiceBlocked(["Purchase order not found."])
    check = check_invoice(session, po)
    if check.excluded:
        raise InvoiceBlocked([check.excluded])
    if check.invoice is not None:
        raise InvoiceBlocked(
            [f"This PO already has QuickBooks invoice {check.invoice.doc_number or check.invoice.qbo_invoice_id}."]
        )
    if check.blockers:
        raise InvoiceBlocked(check.blockers)
    if check.warnings and not send_without_email:
        raise MissingBillEmail(check.warnings)

    # Lines that were unpriced when entered get today's pricing (existing
    # prices are never changed).
    if price_unpriced_lines(session, po_id):
        session.expire_all()
        po = get_purchase_order(session, po_id)

    if len(po.po_number or "") > PO_FIELD_MAX_LENGTH:
        raise InvoiceBlocked(
            [f"The PO number is longer than the {PO_FIELD_MAX_LENGTH} characters a QuickBooks field holds."]
        )
    # The PO number goes in the PO Reference no. field when QuickBooks exposes
    # one through the API; if it doesn't, the invoice is still created and the
    # person enters the PO number by hand (the caller is told).
    po_field, _ = find_po_field(session)

    realm = current_realm(session)
    _, target_link = invoice_target(session, po.customer)
    qbo_customer_id = target_link.qbo_customer_id
    terms = _invoice_terms(session, po.customer, qbo_customer_id)
    total = invoice_total(po)

    # An earlier attempt whose outcome is unknown is retried under the same
    # request id (and the same invoice number), so QuickBooks returns that
    # invoice rather than a second one.
    attempt = session.scalars(
        select(QboInvoice)
        .where(
            QboInvoice.po_id == po_id,
            QboInvoice.realm_id == realm,
            QboInvoice.status == "pending",
        )
        .order_by(QboInvoice.qbo_invoice_record_id.desc())
    ).first()
    if attempt is None:
        attempt = QboInvoice(
            po_id=po_id,
            realm_id=realm,
            request_id=uuid.uuid4().hex,
            status="pending",
            qbo_customer_id=qbo_customer_id,
            doc_number=_invoice_number_for_attempt(session, po_id, realm),
            total_amount=total,
        )
        session.add(attempt)
    else:
        attempt.qbo_customer_id, attempt.total_amount = qbo_customer_id, total
        if not attempt.doc_number:
            attempt.doc_number = next_invoice_number(session)
    session.commit()

    payload = build_invoice_payload(
        po,
        qbo_customer_id,
        current_item_links(session),
        po_field,
        terms,
        resolve_bill_email(po.customer),
        attempt.doc_number,
    )

    try:
        data = qb._request(
            session,
            "POST",
            "invoice",
            json=payload,
            request_id=attempt.request_id,
            params={"include": ENHANCED_CUSTOM_FIELDS} if po_field and po_field[2] else None,
        )
    except qb.QuickBooksError as exc:
        # "Couldn't reach" means the outcome is unknown: leave it pending so a
        # retry reuses the request id. Anything else is a definite refusal.
        if not str(exc).startswith("Couldn't reach"):
            attempt.status = "failed"
        attempt.error = str(exc)
        attempt.intuit_tid = qb.last_intuit_tid()
        session.commit()
        raise
    invoice = data["Invoice"]
    attempt.status = "created"
    attempt.qbo_invoice_id = str(invoice["Id"])
    attempt.doc_number = invoice.get("DocNumber") or attempt.doc_number
    attempt.error = None
    attempt.intuit_tid = qb.last_intuit_tid()
    if attempt.doc_number and not (po.invoice_number or "").strip():
        po.invoice_number = attempt.doc_number
    session.commit()
    session.refresh(attempt)
    attempt.po_number_filled = po_field is not None  # not stored; for the caller's message
    return attempt


def invoice_is_stale(po: PurchaseOrder, invoice: QboInvoice) -> bool:
    """True if the PO's total no longer matches what was invoiced (the invoice
    in QuickBooks isn't updated automatically)."""
    return invoice.total_amount is not None and invoice_total(po) != Decimal(invoice.total_amount)
