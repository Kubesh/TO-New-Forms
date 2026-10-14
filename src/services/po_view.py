"""DRAFT - not installed anywhere yet, and the formula has not been run in Google
Sheets (there's no way to here); expect to adjust it once it has been.

A "view" tab in the PO Google Sheet: one row per PO with a column per
product, laid out like the legacy PO tracker.

The tab is a single formula in A1, built on QUERY, that reads the po_data tab
that po_sheets_sync.py keeps up to date - so it refreshes itself as POs
change and nothing here runs inside the app. scripts/create_po_view.py
installs it.

It's PO Number, Store Key, Order Date, Due Date, Box, Type of order, then one
column per product holding that PO's quantity. Box is left blank (not used).
Voided POs are left out. Products with no column below (the coffees, which
have never been ordered) are not shown at all.
"""
from src.services.po_sheets_sync import HEADERS

# (column heading, SKU), in the order the columns appear. Headings are exactly
# as the legacy tracker has them, including the en dash in the two
# "Drinking Chocolate ... – SUP" ones.
SKU_COLUMNS = [
    ("Drinking Chocolate - Original", "01010110"),
    ("Drinking Chocolate - Mocha", "01020110"),
    ("Drinking Chocolate - Sea Salt", "01030110"),
    ("Drinking Chocolate - Spiced", "01040110"),
    ("Drinking Chocolate - Coconut", "01050110"),
    ("Drinking Chocolate - Original – SUP", "01010205"),
    ("Drinking Chocolate - Coconut – SUP", "01050205"),
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

LEADING_HEADINGS = ["PO Number", "Store Key", "Order Date", "Due Date", "Box", "Type of order"]
VIEW_HEADINGS = LEADING_HEADINGS + [name for name, _ in SKU_COLUMNS]
DATE_VIEW_COLUMNS = (2, 3)  # Order Date, Due Date


def _letter(heading: str) -> str:
    """Column letter in the po_data tab for a po_sheets_sync header."""
    return chr(ord("A") + HEADERS.index(heading))


def _text_array(values: list[str]) -> str:
    return "{" + ",".join('"' + v.replace('"', '""') + '"' for v in values) + "}"


def build_view_formula(source_tab: str) -> str:
    """The formula for cell A1 of the view tab. `source_tab` is the po_data
    tab's name."""
    src = "'" + source_tab.replace("'", "''") + "'"
    po, store, order_date, due_date, order_type, sku, qty, voided = (
        _letter(h)
        for h in ("PO Number", "Store Key", "Order Date", "Due Date", "Order Type", "SKU", "Quantity", "VOIDED")
    )
    last = _letter("Line Item ID")

    query = (
        f"select {po}, {store}, {order_date}, {due_date}, {order_type}, sum({qty}) "
        f"where {sku} is not null and ({voided} = false or {voided} is null) "
        f"group by {po}, {store}, {order_date}, {due_date}, {order_type} "
        f"pivot {sku}"
    )

    # t: the pivoted QUERY - first row is headings (the SKUs, for the pivot
    # columns), the rest one row per PO, with a column only for each SKU that
    # actually appears. The MATCH looks each wanted SKU up in that heading row
    # (wildcard so it still matches if Sheets appends a label to the SKU), so
    # the product columns always come out in the fixed order below, blank
    # where a SKU has no column yet.
    return (
        "=LET("
        f"skus,{_text_array([s for _, s in SKU_COLUMNS])},"
        f"head,{_text_array(VIEW_HEADINGS)},"
        f't,QUERY({src}!A2:{last},"{query}",0),'
        "hdr,INDEX(t,1,0),"
        "data,CHOOSEROWS(t,SEQUENCE(ROWS(t)-1,1,2)),"
        "qty,MAKEARRAY(ROWS(data),COLUMNS(skus),LAMBDA(r,c,"
        'IFERROR(INDEX(data,r,MATCH(INDEX(skus,1,c)&"*",hdr,0)),""))),'
        "IFERROR(VSTACK(head,HSTACK("
        "CHOOSECOLS(data,1,2,3,4),"
        'MAKEARRAY(ROWS(data),1,LAMBDA(r,c,"")),'
        "CHOOSECOLS(data,5),"
        "qty)),head))"
    )
