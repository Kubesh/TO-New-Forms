"""Create the PO "view" tab in the PO Google Sheet.

Usage:
    python scripts/create_po_view.py             # create the tab
    python scripts/create_po_view.py --replace   # clear and recreate it
    python scripts/create_po_view.py --print     # just print the formula

The tab is one formula in A1 (built on QUERY) that lays the po_data tab out
as one row per PO (legacy tracker layout: the PO's fields, then a column per
product) - see src/services/po_view.py.
It keeps itself up to date; there's nothing to re-run when POs change.

Needs the po_data tab to exist (run scripts/sync_pos_to_sheet.py first) and
the GOOGLE_SHEETS_PO_* settings in .env. The tab is named po_view unless
GOOGLE_SHEETS_PO_VIEW_TAB_NAME says otherwise. If you'd rather paste the
formula yourself: --print, then paste the output into cell A1 of an empty tab.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402

from src.services.po_sheets_sync import _service, _spreadsheet_id, _tab_name  # noqa: E402
from src.services.po_view import (  # noqa: E402
    ViewTabExists,
    build_view_formula,
    install_view,
    view_tab_name,
)
from src.services.sheets_sync import SheetsSyncNotConfigured  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--replace", action="store_true", help="clear and recreate the tab if it exists")
    parser.add_argument("--print", dest="print_only", action="store_true", help="print the formula and exit")
    args = parser.parse_args()

    load_dotenv()
    source_tab = _tab_name()
    if args.print_only:
        print(build_view_formula(source_tab))
        return
    try:
        service = _service()
        spreadsheet_id = _spreadsheet_id()
    except SheetsSyncNotConfigured as exc:
        sys.exit(f"Not configured: {exc}")
    view_tab = view_tab_name()
    try:
        install_view(service, spreadsheet_id, source_tab, view_tab, replace=args.replace)
    except ViewTabExists:
        sys.exit(f"The '{view_tab}' tab already exists. Use --replace to clear and recreate it.")
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"Created the '{view_tab}' tab. Open it and check the columns and a few rows against po_data.")


if __name__ == "__main__":
    main()
