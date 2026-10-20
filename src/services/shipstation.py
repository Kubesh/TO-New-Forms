"""ShipStation (classic API, ssapi.shipstation.com) client.

Only what the app needs: push a PO in as an "awaiting shipment" order, and
look up the shipments (labels) ShipStation has created for an order. Auth is
HTTP Basic with the account's API key/secret, from the environment.

No prices are sent - the company doesn't want them in ShipStation - and
everything is assumed domestic (US).
"""
import logging
import os
from datetime import date, datetime
from decimal import Decimal

import requests

from src.models import PurchaseOrder

logger = logging.getLogger(__name__)

BASE_URL = "https://ssapi.shipstation.com"
REQUEST_TIMEOUT_SECONDS = 20

# Domestic only: blank or a spelled-out US country becomes "US"; anything
# else has to already be a 2-letter code, since ShipStation requires one.
_US_COUNTRY_NAMES = {"", "US", "USA", "U.S.", "U.S.A.", "UNITED STATES", "UNITED STATES OF AMERICA"}


class ShipStationNotConfigured(Exception):
    """Raised when the ShipStation env vars haven't been set up yet."""


class ShipStationError(Exception):
    """A problem with the PO's data or with ShipStation's response. The
    message is written to be shown to the user as-is."""


def order_key_for(po: PurchaseOrder, sequence: int = 1) -> str:
    """Unique per send. Each send of a PO is its own order in ShipStation
    (ShipStation updates an existing order when it sees the same orderKey, so
    reusing the key would fold a re-send into the first order and the labels
    couldn't be told apart). The first send keeps the plain "PO-<id>" key."""
    return f"PO-{po.po_id}" if sequence == 1 else f"PO-{po.po_id}-{sequence}"


def order_number_for(po: PurchaseOrder, sequence: int = 1) -> str:
    """ShipStation's visible Order #: the PO number, with a "-2", "-3"... on
    later sends so the orders can be told apart in ShipStation."""
    return po.po_number if sequence == 1 else f"{po.po_number}-{sequence}"


def next_sequence(po: PurchaseOrder, existing_keys: set[str]) -> int:
    """The next unused send number for this PO. Skips any whose key is already
    taken, so a deleted history row can never cause a key to be reused (which
    would update that old order instead of creating a new one)."""
    sequence = len(existing_keys) + 1
    while order_key_for(po, sequence) in existing_keys:
        sequence += 1
    return sequence


def _credentials() -> tuple[str, str]:
    key = os.environ.get("SHIPSTATION_API_KEY")
    secret = os.environ.get("SHIPSTATION_API_SECRET")
    if not key or not secret:
        raise ShipStationNotConfigured(
            "ShipStation isn't set up yet - SHIPSTATION_API_KEY and "
            "SHIPSTATION_API_SECRET need to be set."
        )
    return key, secret


def _country_code(raw: str | None) -> str:
    value = (raw or "").strip()
    if value.upper() in _US_COUNTRY_NAMES:
        return "US"
    if len(value) == 2 and value.isalpha():
        return value.upper()
    raise ShipStationError(
        f"Can't send this order - the customer's shipping country '{value}' isn't a "
        "2-letter country code."
    )


def _address(customer, prefix: str, name: str) -> dict:
    """prefix is 'shipping' or 'billing'."""
    return {
        "name": name,
        "street1": getattr(customer, f"{prefix}_address_line1"),
        "street2": getattr(customer, f"{prefix}_address_line2"),
        "city": getattr(customer, f"{prefix}_city"),
        "state": getattr(customer, f"{prefix}_state"),
        "postalCode": getattr(customer, f"{prefix}_postal_code"),
        "country": _country_code(getattr(customer, f"{prefix}_country")),
    }


def line_weight_lb(line) -> Decimal | None:
    """Weight in pounds of a PO line at its *current* quantity, or None if it
    can't be worked out.

    expanded_weight is the whole line's weight, but only the CSV import ever
    fills it in - editing a quantity in the app doesn't update it and lines
    added in the app don't have one. So it's scaled by current/original
    quantity, which keeps it consistent with the imported figure. Lines with
    no expanded_weight fall back to the item's unit weight x quantity."""
    if line.expanded_weight is not None and line.original_quantity > 0:
        return line.expanded_weight * line.quantity / line.original_quantity
    if line.item is not None and line.item.unit_weight_lb is not None:
        return line.item.unit_weight_lb * line.quantity
    return None


def order_weight_lb(po: PurchaseOrder) -> tuple[Decimal | None, list[str]]:
    """(total weight in pounds, SKUs whose weight is unknown). The total is
    None unless every line with a quantity has a weight: a partial total
    would put an underweight label on the box, so it's left off and the
    weight is entered in ShipStation instead."""
    total = Decimal(0)
    missing: list[str] = []
    for line in po.line_items:
        if line.quantity <= 0:
            continue
        weight = line_weight_lb(line)
        if weight is None:
            missing.append(line.sku or (line.item.sku if line.item else None) or "?")
        else:
            total += weight
    if missing or total <= 0:
        return None, missing
    return total, missing


# How new orders are shipped, chosen on the ShipStation page. Empty means
# ShipStation's own default (its automation rules / whatever is picked there).
SHIPPING_SETTING_KEYS = ("shipstation_carrier_code", "shipstation_service_code", "shipstation_service_name")


def configured_shipping_method(session) -> dict | None:
    """{"carrier_code", "service_code", "name"} for the saved method, or None."""
    from src.services.app_settings import get_settings

    saved = get_settings(session, list(SHIPPING_SETTING_KEYS))
    carrier, service = saved.get("shipstation_carrier_code"), saved.get("shipstation_service_code")
    if not carrier or not service:
        return None
    return {
        "carrier_code": carrier,
        "service_code": service,
        "name": saved.get("shipstation_service_name") or service,
    }


def build_order_payload(po: PurchaseOrder, sequence: int = 1, shipping: dict | None = None) -> dict:
    """The createorder body for a PO. Needs po.customer and the line items
    (and each line's item) loaded - see get_purchase_order.

    Where the identifiers land in ShipStation:
      - orderNumber     -> the PO number (ShipStation's "Order #"), with a
                           "-2", "-3"... suffix on re-sends
      - customField1    -> the PO number again, so it's available as a
                           custom-field column/filter/label field
      - customField2    -> our internal order ID (po_id)
      - customField3    -> reserved for the invoice number; not sent yet
    """
    customer = po.customer
    if customer is None:
        raise ShipStationError("Can't send this order - it isn't linked to a customer.")

    missing = [
        label
        for label, value in (
            ("address", customer.shipping_address_line1),
            ("city", customer.shipping_city),
            ("state", customer.shipping_state),
            ("postal code", customer.shipping_postal_code),
        )
        if not (value or "").strip()
    ]
    if missing:
        raise ShipStationError(
            f"Can't send this order - {customer.customer_name} has no shipping "
            f"{', '.join(missing)}."
        )

    items = []
    for line in po.line_items:
        if line.quantity <= 0:
            continue
        sku = line.sku or (line.item.sku if line.item else None)
        name = (line.item.name if line.item else None) or line.item_description or sku
        items.append({"sku": sku, "name": name or "Item", "quantity": line.quantity})
    if not items:
        raise ShipStationError("Can't send this order - it has no line items with a quantity.")

    ship_to = _address(customer, "shipping", customer.customer_name)
    ship_to["phone"] = customer.phone_number

    # Billing is optional context; fall back to the ship-to when it isn't filled in.
    bill_to = (
        _address(customer, "billing", customer.customer_name)
        if customer.billing_address_line1
        else dict(ship_to)
    )

    advanced_options = {
        "customField1": po.po_number,
        "customField2": str(po.po_id),
    }
    store_id = os.environ.get("SHIPSTATION_STORE_ID")
    if store_id:
        advanced_options["storeId"] = int(store_id)

    payload = {
        "orderNumber": order_number_for(po, sequence),
        "orderKey": order_key_for(po, sequence),
        "orderDate": (po.order_date or date.today()).isoformat(),
        "orderStatus": "awaiting_shipment",
        "billTo": bill_to,
        "shipTo": ship_to,
        "items": items,
        "advancedOptions": advanced_options,
    }
    if shipping:
        payload["carrierCode"] = shipping["carrier_code"]
        payload["serviceCode"] = shipping["service_code"]
    weight_lb, _ = order_weight_lb(po)
    if weight_lb is not None:
        payload["weight"] = {"value": float(round(weight_lb, 3)), "units": "pounds"}
    if po.requested_ship_date:
        payload["shipByDate"] = po.requested_ship_date.isoformat()
    if po.note:
        payload["internalNotes"] = po.note
    return payload


def _request(method: str, path: str, **kwargs) -> dict:
    try:
        response = requests.request(
            method,
            BASE_URL + path,
            auth=_credentials(),
            timeout=REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )
    except requests.RequestException as exc:
        logger.warning("ShipStation request failed: %s", exc)
        raise ShipStationError(f"Couldn't reach ShipStation: {exc}") from exc

    if response.status_code == 401:
        raise ShipStationError("ShipStation rejected the API key/secret (401).")
    if response.status_code == 429:
        raise ShipStationError("ShipStation rate limit hit - wait a minute and try again.")
    if not response.ok:
        try:
            body = response.json()
            detail = body.get("ExceptionMessage") or body.get("Message") or response.text
        except ValueError:
            detail = response.text
        raise ShipStationError(f"ShipStation returned {response.status_code}: {detail}")
    return response.json()


def send_order(po: PurchaseOrder, sequence: int = 1, shipping: dict | None = None) -> dict:
    """Creates a new order in ShipStation for this send of the PO. Returns
    ShipStation's order record, which includes 'orderId'. `shipping` (see
    configured_shipping_method) sets the carrier and service on the order."""
    return _request(
        "POST", "/orders/createorder", json=build_order_payload(po, sequence, shipping)
    )


def list_carriers() -> list[dict]:
    """The carriers on the ShipStation account: [{"code", "name"}]."""
    data = _request("GET", "/carriers")
    return [
        {"code": c.get("code"), "name": c.get("name") or c.get("code")}
        for c in (data if isinstance(data, list) else [])
        if c.get("code")
    ]


def list_services(carrier_code: str) -> list[dict]:
    """A carrier's domestic services: [{"code", "name"}]."""
    data = _request("GET", "/carriers/listservices", params={"carrierCode": carrier_code})
    return [
        {"code": s.get("code"), "name": s.get("name") or s.get("code")}
        for s in (data if isinstance(data, list) else [])
        if s.get("code") and s.get("domestic", True)
    ]


def _parse_timestamp(value: str | None) -> datetime | None:
    # ShipStation sends e.g. "2014-10-03T08:15:00.0000000" (Pacific time).
    # Stored as returned, without conversion.
    if not value:
        return None
    return datetime.fromisoformat(value[:19])


def get_labels_for_order(shipstation_order_id: int) -> list[dict]:
    """The non-voided shipments (labels) ShipStation has for an order, each
    as {tracking_number, carrier_code, label_created_at}. Empty until
    someone creates a label."""
    data = _request("GET", "/shipments", params={"orderId": shipstation_order_id})
    return [
        {
            "tracking_number": shipment.get("trackingNumber"),
            "carrier_code": shipment.get("carrierCode"),
            "label_created_at": _parse_timestamp(shipment.get("createDate")),
        }
        for shipment in data.get("shipments", [])
        if not shipment.get("voided")
    ]


def check_connection() -> list[dict]:
    """The account's stores - a light call that proves the key/secret work."""
    data = _request("GET", "/stores")
    return data if isinstance(data, list) else []
