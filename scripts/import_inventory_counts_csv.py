"""Import historical inventory count records into inventory_counts /
inventory_count_items.

Usage:
    python scripts/import_inventory_counts_csv.py path/to/file.csv [--dry-run]

Expects columns: SKU / Item Number, Timestamp, Email Address, Amount, Notes
("Forced Plain Text Value" is a duplicate of the SKU column and is ignored).

Each row is one item's counted amount at a point in time - there's no
explicit session/batch column. Rows sharing an exact Timestamp are treated
as one inventory count session (one InventoryCount), with each row
becoming one InventoryCountItem under it: verified against the real export
that rows sharing a timestamp always share the same submitter email too,
confirming they're a single batch entry rather than a coincidence. Rows
with a unique timestamp become their own single-item session.

Email Address has no column of its own on either table, so it's folded
into each item's notes as a "[email]" prefix (ahead of the row's own
notes, if any) rather than dropped - clean this up later once there's a
proper place for it.

If a SKU doesn't match an existing item, a stub Item is created (sku only,
name set to the sku) so no count data is lost - these print as
"note: created stub item ..." and should be renamed/cleaned up later.

Safe to re-run: an InventoryCount is reused for a given import timestamp
if one already exists (matched by created_at), and within it, an item
already counted at that timestamp is skipped rather than duplicated.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.models import InventoryCount, InventoryCountItem, Item  # noqa: E402

TIMESTAMP_FORMAT = "%m/%d/%Y %H:%M:%S"


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


def parse_decimal(value: str | None) -> Decimal | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv_path")
    parser.add_argument("--dry-run", action="store_true", help="Report counts, write nothing")
    args = parser.parse_args()

    raw_rows = load_rows(args.csv_path)

    rows = []
    skipped_bad = 0
    for row in raw_rows:
        sku = clean(row.get("SKU / Item Number"))
        ts_raw = clean(row.get("Timestamp"))
        amount = parse_decimal(row.get("Amount"))
        if not sku or not ts_raw or amount is None:
            skipped_bad += 1
            continue
        try:
            timestamp = datetime.strptime(ts_raw, TIMESTAMP_FORMAT)
        except ValueError:
            skipped_bad += 1
            continue
        rows.append(
            {
                "sku": sku,
                "timestamp": timestamp,
                "email": clean(row.get("Email Address")),
                "amount": amount,
                "notes": clean(row.get("Notes")),
            }
        )

    groups: dict[datetime, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["timestamp"]].append(row)

    session = get_session()
    try:
        all_skus = {row["sku"] for row in rows}
        items = {
            item.sku: item for item in session.scalars(select(Item).where(Item.sku.in_(all_skus)))
        }
        stub_items_created = 0
        for sku in sorted(all_skus - items.keys()):
            item = Item(sku=sku, name=sku)
            session.add(item)
            session.flush()
            items[sku] = item
            stub_items_created += 1
            print(f"note: created stub item for unmatched SKU {sku!r} - rename it later")

        existing_counts = {c.created_at: c for c in session.scalars(select(InventoryCount))}
        existing_items = {
            (ci.inventory_count_id, ci.item_id)
            for ci in session.scalars(select(InventoryCountItem))
        }

        counts_created = 0
        counts_reused = 0
        items_created = 0
        items_skipped_dupe = 0

        for timestamp in sorted(groups):
            group_rows = groups[timestamp]
            count = existing_counts.get(timestamp)
            if count is None:
                count = InventoryCount(created_at=timestamp, updated_at=timestamp)
                session.add(count)
                session.flush()
                existing_counts[timestamp] = count
                counts_created += 1
            else:
                counts_reused += 1

            for row in group_rows:
                item = items[row["sku"]]
                key = (count.inventory_count_id, item.item_id)
                if key in existing_items:
                    items_skipped_dupe += 1
                    continue
                notes = f"[{row['email']}]" if row["email"] else None
                if row["notes"]:
                    notes = f"{notes} {row['notes']}" if notes else row["notes"]
                session.add(
                    InventoryCountItem(
                        inventory_count_id=count.inventory_count_id,
                        item_id=item.item_id,
                        counted=row["amount"],
                        notes=notes,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                existing_items.add(key)
                items_created += 1

        print(f"Rows in CSV: {len(raw_rows)}")
        print(f"Rows skipped (missing SKU/timestamp/amount): {skipped_bad}")
        print(f"Distinct count sessions (by timestamp): {len(groups)}")
        print(f"Stub items created: {stub_items_created}")
        print(f"InventoryCounts created: {counts_created}")
        print(f"InventoryCounts reused (already imported): {counts_reused}")
        print(f"InventoryCountItems created: {items_created}")
        print(f"InventoryCountItems skipped (already imported): {items_skipped_dupe}")

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
