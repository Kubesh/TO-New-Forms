"""Keeps a Google Sheet in step with purchase orders: one row per PO line item,
with the PO header's dates and store key repeated on each row.

This is a different spreadsheet from the customers sync in sheets_sync.py, so
it has its own env vars (GOOGLE_SHEETS_PO_*). It shares that module's
service-account client; set GOOGLE_SHEETS_PO_CREDENTIALS_FILE only if this
sheet needs different credentials.

Rows are matched by the trailing "Line Item ID" column, not by PO number or
SKU, so editing a PO or repeating a SKU on one PO can't mix rows up. That
column is a helper for the sync - it can be hidden in the sheet, but not
deleted or reordered.

Voided POs stay in the sheet, with TRUE in the VOIDED column (FALSE for
everything else) so legacy tools can filter on it; a PO's rows are only removed
if the PO is deleted from the app. Everything is written as RAW, so a SKU
like "1-2" or a PO number can never be reinterpreted as a date or formula;
dates are written as sheet date serials and the date columns are formatted
once, when the header row is first created.
"""
import logging
import os
from datetime import date, datetime

from src.models import PurchaseOrder
from src.services.sheets_sync import SheetsSyncNotConfigured, build_service

logger = logging.getLogger(__name__)

HEADERS = [
    "Ship Date",
    "PO Number",
    "Store Key",
    "SKU",
    "Quantity",
    "Order Date",
    "Due Date",
    "VOIDED",
    "Line Item ID",
]
# The layout before the VOIDED column existed. A sheet still carrying it gets
# VOIDED inserted ahead of Line Item ID the first time it's synced.
LEGACY_HEADERS = [h for h in HEADERS if h != "VOIDED"]
VOIDED_COLUMN = HEADERS.index("VOIDED")
DATE_COLUMNS = (0, 5, 6)  # Ship Date, Order Date, Due Date
KEY_COLUMN = len(HEADERS) - 1
LAST_COLUMN_LETTER = chr(ord("A") + len(HEADERS) - 1)

# (spreadsheet_id, tab) -> sheetId, for tabs already checked/created this
# process, so each sync after the first skips the setup calls.
_ready: dict[tuple[str, str], int] = {}


def _service():
    creds_file = os.environ.get("GOOGLE_SHEETS_PO_CREDENTIALS_FILE") or os.environ.get(
        "GOOGLE_SHEETS_CREDENTIALS_FILE"
    )
    if not creds_file:
        raise SheetsSyncNotConfigured(
            "GOOGLE_SHEETS_PO_CREDENTIALS_FILE (or GOOGLE_SHEETS_CREDENTIALS_FILE) is not set."
        )
    return build_service(creds_file)


def _spreadsheet_id() -> str:
    spreadsheet_id = os.environ.get("GOOGLE_SHEETS_PO_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise SheetsSyncNotConfigured("GOOGLE_SHEETS_PO_SPREADSHEET_ID is not set.")
    return spreadsheet_id


def _tab_name() -> str:
    return os.environ.get("GOOGLE_SHEETS_PO_TAB_NAME", "po_data")


def _a1(tab: str, cells: str) -> str:
    """A1 range with the tab name quoted, so names with spaces work."""
    return "'" + tab.replace("'", "''") + "'!" + cells


def _serial(value: date | datetime | None):
    """A Sheets date serial (days since 1899-12-30), or "" for no date."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    return (value - date(1899, 12, 30)).days


def _po_rows(po: PurchaseOrder) -> list[tuple[int, list]]:
    """(line_item_id, row values) for each line item on the PO. Needs
    po.customer and the line items (and each line's item) loaded."""
    # The customer's current store key; the PO's own store_key is the legacy
    # value from before store keys lived on the customer.
    if po.customer is not None and po.customer.store_key is not None:
        store_key = po.customer.store_key
    else:
        store_key = po.store_key if po.store_key is not None else ""

    # The sheet shows PO numbers as "#1234"; don't double it if the number is
    # already stored with its "#".
    po_number = po.po_number if po.po_number.startswith("#") else f"#{po.po_number}"

    rows = []
    for line in po.line_items:
        sku = line.sku or (line.item.sku if line.item else None) or ""
        rows.append(
            (
                line.line_item_id,
                [
                    _serial(po.ship_date),
                    po_number,
                    store_key,
                    sku,
                    line.quantity,
                    _serial(po.order_date),
                    _serial(po.due_date),
                    bool(po.voided),
                    line.line_item_id,
                ],
            )
        )
    return rows


def _prepare(service, spreadsheet_id: str, tab: str) -> int:
    """Makes sure the tab exists and has its header row (and date formats);
    returns the tab's sheetId."""
    cached = _ready.get((spreadsheet_id, tab))
    if cached is not None:
        return cached

    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)")
        .execute()
    )
    sheet_id = next(
        (
            sheet["properties"]["sheetId"]
            for sheet in meta.get("sheets", [])
            if sheet["properties"]["title"] == tab
        ),
        None,
    )
    if sheet_id is None:
        reply = (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
            )
            .execute()
        )
        sheet_id = reply["replies"][0]["addSheet"]["properties"]["sheetId"]

    header = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=_a1(tab, f"A1:{LAST_COLUMN_LETTER}1"))
        .execute()
    )
    header_row = (header.get("values") or [[]])[0]
    if header_row == LEGACY_HEADERS:
        # inheritFromBefore=False so the new column doesn't pick up the date
        # format of the Due Date column beside it.
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "insertDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": VOIDED_COLUMN,
                                "endIndex": VOIDED_COLUMN + 1,
                            },
                            "inheritFromBefore": False,
                        }
                    }
                ]
            },
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=_a1(tab, f"{chr(ord('A') + VOIDED_COLUMN)}1"),
            valueInputOption="RAW",
            body={"values": [["VOIDED"]]},
        ).execute()
        # The inserted column is blank down the existing rows; they're all
        # live POs as far as this sheet knows (voided rows used to be removed),
        # so fill in FALSE now rather than leaving gaps until each PO is saved.
        key_column = _a1(tab, f"{LAST_COLUMN_LETTER}:{LAST_COLUMN_LETTER}")
        keys = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=key_column)
            .execute()
            .get("values", [])
        )
        if len(keys) > 1:
            voided_letter = chr(ord("A") + VOIDED_COLUMN)
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=_a1(tab, f"{voided_letter}2:{voided_letter}{len(keys)}"),
                valueInputOption="RAW",
                body={"values": [[False]] * (len(keys) - 1)},
            ).execute()
        logger.info("PO sheet: added the VOIDED column to an existing sheet")
    elif not header_row:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=_a1(tab, "A1"),
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": column,
                        "endColumnIndex": column + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "DATE", "pattern": "mm/dd/yyyy"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
            for column in DATE_COLUMNS
        ]
        requests.append(
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            }
        )
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            }
        )
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    _ready[(spreadsheet_id, tab)] = sheet_id
    return sheet_id


def _existing_rows(service, spreadsheet_id: str, tab: str) -> dict[str, int]:
    """line_item_id (as text) -> 1-indexed sheet row, from the key column."""
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=_a1(tab, f"{LAST_COLUMN_LETTER}:{LAST_COLUMN_LETTER}"),
        )
        .execute()
    )
    rows: dict[str, int] = {}
    for row_number, row in enumerate(result.get("values", []), start=1):
        if row_number > 1 and row and str(row[0]).strip():
            rows[str(row[0]).strip()] = row_number
    return rows


def _delete_rows(service, spreadsheet_id: str, sheet_id: int, row_numbers: list[int]) -> None:
    # Highest row first, so deleting one doesn't shift the rest.
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_number - 1,
                            "endIndex": row_number,
                        }
                    }
                }
                for row_number in sorted(set(row_numbers), reverse=True)
            ]
        },
    ).execute()


def sync_purchase_orders(pos: list[PurchaseOrder]) -> None:
    """Create/update the sheet rows for these POs' line items - voided POs
    included, flagged in the VOIDED column. Works the same for one PO or all
    of them: a handful of API calls either way.

    Raises SheetsSyncNotConfigured if the PO sheet's env vars aren't set
    (callers treat that as "feature not enabled"), or the Google API error on
    any other failure - callers should catch broadly, since a sync failure
    shouldn't block saving the PO itself.
    """
    service = _service()
    spreadsheet_id = _spreadsheet_id()
    tab = _tab_name()
    _prepare(service, spreadsheet_id, tab)
    existing = _existing_rows(service, spreadsheet_id, tab)

    updates: list[dict] = []
    appends: list[list] = []
    for po in pos:
        for line_item_id, values in _po_rows(po):
            row_number = existing.get(str(line_item_id))
            if row_number is not None:
                updates.append(
                    {
                        "range": _a1(tab, f"A{row_number}:{LAST_COLUMN_LETTER}{row_number}"),
                        "values": [values],
                    }
                )
            else:
                appends.append(values)

    values_api = service.spreadsheets().values()
    if updates:
        values_api.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": updates},
        ).execute()
    if appends:
        values_api.append(
            spreadsheetId=spreadsheet_id,
            range=_a1(tab, "A1"),
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": appends},
        ).execute()
    logger.info("PO sheet sync: %d updated, %d added", len(updates), len(appends))


def sync_purchase_order(po: PurchaseOrder) -> None:
    sync_purchase_orders([po])


def remove_line_items(line_item_ids: list[int]) -> None:
    """Removes the sheet rows for these line items. For when a PO is deleted
    from the app (only possible once it's voided and unshipped), so it doesn't
    leave orphaned rows behind. Ids that have no row are ignored."""
    if not line_item_ids:
        return
    service = _service()
    spreadsheet_id = _spreadsheet_id()
    tab = _tab_name()
    sheet_id = _prepare(service, spreadsheet_id, tab)
    existing = _existing_rows(service, spreadsheet_id, tab)
    rows = [existing[str(i)] for i in line_item_ids if str(i) in existing]
    if rows:
        _delete_rows(service, spreadsheet_id, sheet_id, rows)
    logger.info("PO sheet sync: %d removed", len(rows))
