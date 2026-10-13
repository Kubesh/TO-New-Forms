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


def order_key_for(po: PurchaseOrder) -> str:
    """Stable per-PO key. ShipStation updates the existing order when it
    gets the same orderKey again, so re-sending a PO (e.g. after editing
    it) updates its order rather than creating a duplicate."""
    return f"PO-{po.po_id}"


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


def build_order_payload(po: PurchaseOrder) -> dict:
    """The createorder body for a PO. Needs po.customer and the line items
    (and each line's item) loaded - see get_purchase_order.

    Where the identifiers land in ShipStation:
      - orderNumber     -> the PO number (ShipStation's "Order #")
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
        "orderNumber": po.po_number,
        "orderKey": order_key_for(po),
        "orderDate": (po.order_date or date.today()).isoformat(),
        "orderStatus": "awaiting_shipment",
        "billTo": bill_to,
        "shipTo": ship_to,
        "items": items,
        "advancedOptions": advanced_options,
    }
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


def send_order(po: PurchaseOrder) -> dict:
    """Creates (or updates, by orderKey) the PO's order in ShipStation.
    Returns ShipStation's order record, which includes 'orderId'."""
    return _request("POST", "/orders/createorder", json=build_order_payload(po))


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
