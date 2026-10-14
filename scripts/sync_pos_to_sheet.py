"""Push every purchase order's line items to the PO Google Sheet.

Usage:
    python scripts/sync_pos_to_sheet.py [--dry-run]

The app syncs a PO whenever it's created, edited, or shipped, so this is for
the initial load of the POs that already exist, and for repairs: it also
refreshes rows that have gone stale because something the sheet shows was
changed elsewhere (a customer's store key, an item's SKU, a CSV re-import).

Safe to re-run: rows are matched by Line Item ID, so existing rows are
updated in place and only new line items are appended. Voided POs are included,
flagged in the VOIDED column. Needs the GOOGLE_SHEETS_PO_* settings in .env.
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import joinedload, selectinload, sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.models import PurchaseOrder, PurchaseOrderLineItem  # noqa: E402
from src.services.po_sheets_sync import sync_purchase_orders  # noqa: E402
from src.services.sheets_sync import SheetsSyncNotConfigured  # noqa: E402


def get_session():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and add your Neon "
            "connection string."
        )
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return sessionmaker(bind=engine)()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="count what would be synced, change nothing")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    session = get_session()
    try:
        pos = list(
            session.scalars(
                select(PurchaseOrder)
                .options(
                    joinedload(PurchaseOrder.customer),
                    selectinload(PurchaseOrder.line_items).joinedload(PurchaseOrderLineItem.item),
                )
                .order_by(PurchaseOrder.po_id)
            )
            .unique()
            .all()
        )
        live = [po for po in pos if not po.voided]
        lines = sum(len(po.line_items) for po in live)
        print(f"{len(pos)} POs ({len(live)} not voided, {lines} line items)")
        if args.dry_run:
            return
        try:
            sync_purchase_orders(pos)
        except SheetsSyncNotConfigured as exc:
            sys.exit(f"Not configured: {exc}")
        print("Done.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
