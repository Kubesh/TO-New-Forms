"""The formula has not been run in Google Sheets (there's no way to here), so
check the tab after installing it and tell me what it shows.

A "view" tab in the PO Google Sheet laid out like the legacy PO tracker: one
row per PO, the PO's own fields first, then a column per product holding that
PO's quantity.

The tab is a single formula in A1, built on QUERY, that reads the po_data tab
that po_sheets_sync.py keeps up to date - so it refreshes itself as POs
change and nothing here runs inside the app. scripts/create_po_view.py
installs it.

Every PO is listed, voided ones included (the Voided? column says which).
Timestamp shows the Order Date. Columns the app doesn't track - Notes, Weight,
Total Order Amount, Invoice Number, Box, Promotion Number, Sales Rep -
Commission - are present for the layout and left blank: po_data doesn't carry
them. Total Quantities
adds up every line on the PO, including any product with no column of its own.
"""
import os

from src.services.po_sheets_sync import HEADERS, _a1

# (column heading, SKU), in the order the product columns appear. Headings are
# exactly as the legacy tracker has them, including the en dash in the two
# "Drinking Chocolate ... \u2013 SUP" ones.
SKU_COLUMNS = [
    ("Drinking Chocolate - Original", "01010110"),
    ("Drinking Chocolate - Mocha", "01020110"),
    ("Drinking Chocolate - Sea Salt", "01030110"),
    ("Drinking Chocolate - Spiced", "01040110"),
    ("Drinking Chocolate - Coconut", "01050110"),
    ("Drinking Chocolate - Original \u2013 SUP", "01010205"),
    ("Drinking Chocolate - Coconut \u2013 SUP", "01050205"),
    ("Creamer - Original", "02010205"),
    ("Creamer - Cinnamon", "02020205"),
    ("Creamer - Cacao", "02030205"),
    ("Creamer - Vanilla", "02040205"),
    ("Oatmeal - Original (NO LONGER SOLD)", "03010110"),
    ("Oatmeal - Turmeric (NO LONGER SOLD)", "03020110"),
    ("Oatmeal - Cacao (NO LONGER SOLD)", "03030110"),
    ("Oatmeal - Original - SUP", "03010305"),
    ("Oatmeal - Turmeric - SUP", "03020305"),
    ("Oatmeal - Cinnamon - SUP", "03040305"),
]

TOTAL = object()  # marks the Total Quantities column in LEADING_COLUMNS

# The po_data columns the QUERY groups by - one output row per distinct
# combination, i.e. per PO - in the order they come out of the QUERY.
GROUP_COLUMNS = ["Ship Date", "PO Number", "Store Key", "Order Date", "Due Date", "Order Type", "VOIDED"]

# The columns before the products, left to right: (heading, where it comes
# from). A po_data heading takes that grouped column, TOTAL is the PO's summed
# quantity, None is left blank.
LEADING_COLUMNS = [
    ("Ship Date", "Ship Date"),
    ("PO Number", "PO Number"),
    ("Store Key", "Store Key"),
    ("Order Date", "Order Date"),
    ("Due Date", "Due Date"),
    ("Timestamp", "Order Date"),  # the legacy tracker's Timestamp is just the order date here
    ("Notes", None),
    ("Total Quantities", TOTAL),
    ("Total Order Amount", None),
    ("Invoice Number", None),
    ("Box", None),
    ("Weight", None),
    ("Type of order", "Order Type"),
    ("Promotion Number", None),
    ("Voided?", "VOIDED"),
    ("Sales Rep - Commission", None),
]
VIEW_HEADINGS = [heading for heading, _ in LEADING_COLUMNS] + [name for name, _ in SKU_COLUMNS]
DATE_VIEW_COLUMNS = tuple(i for i, (h, src) in enumerate(LEADING_COLUMNS) if src in ("Ship Date", "Order Date", "Due Date"))


def _letter(heading: str) -> str:
    """Column letter in the po_data tab for a po_sheets_sync header."""
    return chr(ord("A") + HEADERS.index(heading))


def _text_array(values: list[str]) -> str:
    return "{" + ",".join('"' + v.replace('"', '""') + '"' for v in values) + "}"


def build_view_formula(source_tab: str) -> str:
    """The formula for cell A1 of the view tab. `source_tab` is the po_data
    tab's name."""
    src = "'" + source_tab.replace("'", "''") + "'"
    sku, qty = _letter("SKU"), _letter("Quantity")
    last = _letter("Line Item ID")
    group = [_letter(h) for h in GROUP_COLUMNS]
    # Group (and so sort) by PO Number first.
    group_order = [_letter("PO Number")] + [g for g in group if g != _letter("PO Number")]

    query = (
        f"select {', '.join(group)}, sum({qty}) "
        f"where {sku} is not null "
        f"group by {', '.join(group_order)} "
        f"pivot {sku}"
    )

    # Each leading column as an expression over `data`.
    def column(source):
        if source is TOTAL:
            return "tot"
        if source is None:
            return "bl"
        return f"CHOOSECOLS(data,{GROUP_COLUMNS.index(source) + 1})"

    n = len(GROUP_COLUMNS)
    # t: the pivoted QUERY - first row is headings (the SKUs, for the pivot
    # columns), the rest one row per PO, with a column only for each SKU that
    # actually appears. `data` is those PO rows. The MATCH looks each wanted
    # SKU up in the heading row (wildcard so it still matches if Sheets
    # appends a label to the SKU), so the product columns always come out in
    # the fixed order, blank where a SKU has no column yet. `tot` sums every
    # pivoted column of a row - all products, not just the ones shown.
    return (
        "=LET("
        f"skus,{_text_array([s for _, s in SKU_COLUMNS])},"
        f"head,{_text_array(VIEW_HEADINGS)},"
        f't,QUERY({src}!A2:{last},"{query}",0),'
        "hdr,INDEX(t,1,0),"
        "data,CHOOSEROWS(t,SEQUENCE(ROWS(t)-1,1,2)),"
        'bl,MAKEARRAY(ROWS(data),1,LAMBDA(r,c,"")),'
        f"tot,BYROW(CHOOSECOLS(data,SEQUENCE(1,COLUMNS(data)-{n},{n + 1})),LAMBDA(r,SUM(r))),"
        "qty,MAKEARRAY(ROWS(data),COLUMNS(skus),LAMBDA(r,c,"
        'IFERROR(INDEX(data,r,MATCH(INDEX(skus,1,c)&"*",hdr,0)),""))),'
        "IFERROR(VSTACK(head,HSTACK("
        + ",".join(column(source) for _, source in LEADING_COLUMNS)
        + ",qty)),head))"
    )


def view_tab_name() -> str:
    return os.environ.get("GOOGLE_SHEETS_PO_VIEW_TAB_NAME", "po_view")


class ViewTabExists(Exception):
    """The view tab is already there; installing would overwrite it."""


def install_view(service, spreadsheet_id: str, source_tab: str, view_tab: str, replace: bool = False) -> None:
    """Creates the view tab with the formula in A1 (and date formats, a bold
    frozen heading row). Refuses to touch an existing tab unless replace=True,
    since the formula spills across the tab and anything else in the way would
    block it - and clearing someone's edits isn't this function's call."""
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)")
        .execute()
    )
    tabs = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in meta.get("sheets", [])}
    if source_tab not in tabs:
        raise ValueError(f"The source tab '{source_tab}' doesn't exist in this spreadsheet yet.")
    if view_tab in tabs and not replace:
        raise ViewTabExists(view_tab)
    if view_tab in tabs:
        sheet_id = tabs[view_tab]
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=_a1(view_tab, "A:ZZ"), body={}
        ).execute()
    else:
        reply = (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": view_tab}}}]},
            )
            .execute()
        )
        sheet_id = reply["replies"][0]["addSheet"]["properties"]["sheetId"]

    # USER_ENTERED so Sheets parses it as a formula (the API takes the US
    # comma-separated syntax whatever the spreadsheet's locale).
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=_a1(view_tab, "A1"),
        valueInputOption="USER_ENTERED",
        body={"values": [[build_view_formula(source_tab)]]},
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
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "mm/dd/yyyy"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        }
        for column in DATE_VIEW_COLUMNS
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
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        }
    )
    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
