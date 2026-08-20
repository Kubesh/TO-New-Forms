import logging
import os
from functools import lru_cache

from google.oauth2 import service_account
from googleapiclient.discovery import build

from src.models import Customer

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column order written to the sheet - keep in sync with _customer_row below.
HEADERS = [
    "Customer ID",
    "Customer Name",
    "Type",
    "Store Key",
    "Phone",
    "Shipping Address 1",
    "Shipping Address 2",
    "Shipping City",
    "Shipping State",
    "Shipping Postal Code",
    "Shipping Country",
    "Notes",
    "Archived",
]


class SheetsSyncNotConfigured(Exception):
    """Raised when the Google Sheets env vars haven't been set up yet."""


@lru_cache(maxsize=1)
def _get_service():
    creds_file = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE")
    if not creds_file:
        raise SheetsSyncNotConfigured("GOOGLE_SHEETS_CREDENTIALS_FILE is not set.")
    credentials = service_account.Credentials.from_service_account_file(
        creds_file, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _spreadsheet_id() -> str:
    spreadsheet_id = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise SheetsSyncNotConfigured("GOOGLE_SHEETS_SPREADSHEET_ID is not set.")
    return spreadsheet_id


def _tab_name() -> str:
    return os.environ.get("GOOGLE_SHEETS_TAB_NAME", "streamlit_data")


def _customer_row(customer: Customer) -> list:
    return [
        customer.customer_id,
        customer.customer_name,
        customer.customer_type.name if customer.customer_type else "",
        customer.store_key if customer.store_key is not None else "",
        customer.phone_number or "",
        customer.shipping_address_line1 or "",
        customer.shipping_address_line2 or "",
        customer.shipping_city or "",
        customer.shipping_state or "",
        customer.shipping_postal_code or "",
        customer.shipping_country or "",
        customer.notes or "",
        "Yes" if customer.archived else "",
    ]


def _ensure_headers(service, spreadsheet_id: str, tab: str) -> None:
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{tab}!A1:{_last_col()}1")
        .execute()
    )
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()


def _last_col() -> str:
    """Spreadsheet column letter for the last header (A=1, ... Z=26)."""
    n = len(HEADERS)
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _find_row(service, spreadsheet_id: str, tab: str, customer_id: int) -> int | None:
    """1-indexed sheet row number already holding this customer_id, or None."""
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{tab}!A:A")
        .execute()
    )
    for i, row in enumerate(result.get("values", []), start=1):
        if row and str(row[0]) == str(customer_id):
            return i
    return None


def sync_customer(customer: Customer) -> None:
    """Create or update this customer's row in the tracking spreadsheet.

    Raises SheetsSyncNotConfigured if the env vars aren't set (treated by
    callers as "feature not enabled yet"), or the underlying Google API
    exception on any other failure - callers should catch broadly, since a
    sync failure shouldn't block saving the customer record itself.
    """
    service = _get_service()
    spreadsheet_id = _spreadsheet_id()
    tab = _tab_name()

    _ensure_headers(service, spreadsheet_id, tab)
    row_values = _customer_row(customer)
    existing_row = _find_row(service, spreadsheet_id, tab, customer.customer_id)

    if existing_row is not None:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!A{existing_row}",
            valueInputOption="RAW",
            body={"values": [row_values]},
        ).execute()
    else:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row_values]},
        ).execute()
