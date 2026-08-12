"""Import historical purchase orders into po_headers / po_line_items.

Usage:
    python scripts/import_purchase_orders_csv.py po_headers.csv po_line_items.csv [--dry-run]

Run scripts/import_items_csv.py first - line items are matched to
items by SKU, and scripts/import_customers_csv.py first too - POs are
matched to customers by store_key.

po_headers.csv expects: PO Number, Store Key, Store Name, Street,
City, State, Zip, Chain Name, Account Type, Ship Date, Order Date,
Due Date, Order Entry Timestamp, Note, Voided. Only PO Number,
Store Key, Account Type, the date fields, Note, and Voided are kept -
the store/address columns are dropped since that's already on the
matching customer record.

po_line_items.csv expects: PO Number, SKU, Item Description,
Quantity, Expanded Weight, Box, Unique ID, Shopify Item #. Unique ID
is not reliably unique in the source data, so it isn't used as a key -
instead, re-running this script replaces all line items for every PO
present in the line items CSV (delete-then-insert per PO), which
keeps re-imports idempotent without depending on that field.

Safe to re-run: headers are upserted by po_number; line items are
fully replaced per PO.
"""
import argparse
import csv
import os
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.models import Customer, Item, PurchaseOrder, PurchaseOrderLineItem  # noqa: E402

DATE_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y")


def get_session():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and add your Neon "
            "connection string."
        )
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return sessionmaker(bind=engine)()


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_date(value: str | None):
    value = clean(value)
    if value is None or value.lower() == "voided":
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: str | None):
    value = clean(value)
    if value is None:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_decimal(value: str | None) -> Decimal | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def parse_shopify_number(value: str | None) -> str | None:
    value = clean(value)
    if value is None:
        return None
    value = value.rstrip(":").strip()
    if not value or value == "#N/A":
        return None
    return value


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def import_headers(session, header_rows: list[dict]) -> tuple[dict[str, int], dict]:
    rows = [r for r in header_rows if clean(r.get("PO Number"))]
    skipped_blank = len(header_rows) - len(rows)

    store_keys = {int(r["Store Key"]) for r in rows if clean(r.get("Store Key"))}
    customer_by_store_key = {
        c.store_key: c.customer_id
        for c in session.scalars(select(Customer).where(Customer.store_key.in_(store_keys)))
    }

    po_numbers = [r["PO Number"].strip() for r in rows]
    existing = {
        po.po_number: po
        for po in session.scalars(select(PurchaseOrder).where(PurchaseOrder.po_number.in_(po_numbers)))
    }

    created = 0
    updated = 0
    unmatched_store_keys: set[int] = set()
    new_pos: list[PurchaseOrder] = []

    for row in rows:
        po_number = row["PO Number"].strip()
        store_key = int(row["Store Key"]) if clean(row.get("Store Key")) else None
        customer_id = customer_by_store_key.get(store_key) if store_key is not None else None
        if store_key is not None and customer_id is None:
            unmatched_store_keys.add(store_key)

        fields = dict(
            customer_id=customer_id,
            store_key=store_key,
            order_type=clean(row.get("Account Type")),
            order_date=parse_date(row.get("Order Date")),
            due_date=parse_date(row.get("Due Date")),
            ship_date=parse_date(row.get("Ship Date")),
            order_entry_timestamp=parse_datetime(row.get("Order Entry Timestamp")),
            note=clean(row.get("Note")),
            voided=clean(row.get("Voided")) == "TRUE",
        )

        po = existing.get(po_number)
        if po:
            for key, value in fields.items():
                setattr(po, key, value)
            updated += 1
        else:
            po = PurchaseOrder(po_number=po_number, **fields)
            session.add(po)
            new_pos.append(po)
            created += 1

    if new_pos:
        session.flush()

    po_id_by_number = {po.po_number: po.po_id for po in existing.values()}
    po_id_by_number.update({po.po_number: po.po_id for po in new_pos})

    stats = dict(
        total_rows=len(header_rows),
        skipped_blank=skipped_blank,
        created=created,
        updated=updated,
        unmatched_store_keys=sorted(unmatched_store_keys),
    )
    return po_id_by_number, stats


def import_line_items(session, line_rows: list[dict], po_id_by_number: dict[str, int]) -> dict:
    rows = [r for r in line_rows if clean(r.get("PO Number")) and clean(r.get("SKU"))]
    fully_blank = sum(
        1 for r in line_rows if not clean(r.get("PO Number")) and not clean(r.get("SKU"))
    )
    blank_sku_only = sum(
        1 for r in line_rows if clean(r.get("PO Number")) and not clean(r.get("SKU"))
    )

    skus = {r["SKU"].strip() for r in rows}
    item_id_by_sku = {
        item.sku: item.item_id
        for item in session.scalars(select(Item).where(Item.sku.in_(skus)))
    }
    unmatched_skus = skus - item_id_by_sku.keys()

    rows_by_po_number: dict[str, list[dict]] = {}
    orphan_po_numbers: set[str] = set()
    for row in rows:
        po_number = row["PO Number"].strip()
        if po_number not in po_id_by_number:
            orphan_po_numbers.add(po_number)
            continue
        rows_by_po_number.setdefault(po_number, []).append(row)

    touched_po_ids = [po_id_by_number[num] for num in rows_by_po_number]
    if touched_po_ids:
        session.query(PurchaseOrderLineItem).filter(
            PurchaseOrderLineItem.po_id.in_(touched_po_ids)
        ).delete(synchronize_session=False)

    inserted = 0
    for po_number, po_rows in rows_by_po_number.items():
        po_id = po_id_by_number[po_number]
        for row in po_rows:
            sku = row["SKU"].strip()
            session.add(
                PurchaseOrderLineItem(
                    po_id=po_id,
                    item_id=item_id_by_sku.get(sku),
                    sku=sku,
                    item_description=clean(row.get("Item Description")),
                    quantity=parse_decimal(row.get("Quantity")) or Decimal("0"),
                    expanded_weight=parse_decimal(row.get("Expanded Weight")),
                    box=clean(row.get("Box")),
                    shopify_item_number=parse_shopify_number(row.get("Shopify Item #")),
                )
            )
            inserted += 1

    return dict(
        total_rows=len(line_rows),
        fully_blank_skipped=fully_blank,
        blank_sku_skipped=blank_sku_only,
        pos_replaced=len(rows_by_po_number),
        line_items_inserted=inserted,
        unmatched_skus=sorted(unmatched_skus),
        orphan_po_numbers=sorted(orphan_po_numbers),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("po_headers_csv")
    parser.add_argument("po_line_items_csv")
    parser.add_argument("--dry-run", action="store_true", help="Report counts, write nothing")
    args = parser.parse_args()

    header_rows = load_rows(args.po_headers_csv)
    line_rows = load_rows(args.po_line_items_csv)

    session = get_session()
    try:
        po_id_by_number, header_stats = import_headers(session, header_rows)
        line_stats = import_line_items(session, line_rows, po_id_by_number)

        print("=== Headers ===")
        print(f"Rows in CSV: {header_stats['total_rows']}")
        print(f"Rows skipped (no PO Number): {header_stats['skipped_blank']}")
        print(f"POs created: {header_stats['created']}")
        print(f"POs updated: {header_stats['updated']}")
        if header_stats["unmatched_store_keys"]:
            n = len(header_stats["unmatched_store_keys"])
            print(f"store_keys with no matching customer: {n}")
            for key in header_stats["unmatched_store_keys"][:20]:
                print(f"  - {key}")

        print("\n=== Line items ===")
        print(f"Rows in CSV: {line_stats['total_rows']}")
        print(f"Rows skipped (fully blank): {line_stats['fully_blank_skipped']}")
        print(f"Rows skipped (PO present, no SKU): {line_stats['blank_sku_skipped']}")
        print(f"POs whose line items were replaced: {line_stats['pos_replaced']}")
        print(f"Line items inserted: {line_stats['line_items_inserted']}")
        if line_stats["unmatched_skus"]:
            n = len(line_stats["unmatched_skus"])
            print(f"SKUs with no matching item (line item still created, item_id left null): {n}")
            for sku in line_stats["unmatched_skus"][:20]:
                print(f"  - {sku}")
        if line_stats["orphan_po_numbers"]:
            n = len(line_stats["orphan_po_numbers"])
            print(f"Line items whose PO Number matches no header (skipped): {n}")
            for num in line_stats["orphan_po_numbers"][:20]:
                print(f"  - {num}")

        if args.dry_run:
            session.rollback()
            print("\nDry run - nothing was written.")
        else:
            session.commit()
            print("\nCommitted.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
