"""Import the legacy store-location CSV into customers / customer_contacts.

Usage:
    python scripts/import_customers_csv.py path/to/file.csv [--dry-run]

Expects columns: store_key, customer_name, notes, customer_type_id,
billing_address_line1, billing_city, billing_state, billing_postal_code,
Contact Name. Other columns (Phone Number, Region, Contact Email) are
ignored on purpose -- there's nowhere to put them in the current schema.

The 'notes' column is a chain/banner name shared across many rows (e.g.
"Publix", "Whole Foods"). For each distinct banner, a parent customer
record is created (customer_type = "Parent Account") and every store
row with that banner gets its parent_id pointed at it.

Safe to re-run: stores are upserted by store_key, banner parents are
reused by (customer_name, customer_type_id) if they already exist, and
contacts are only created if a matching (customer_id, contact_name)
pair doesn't already exist.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select  # noqa: E402

from src.db import session_scope  # noqa: E402
from src.models import Customer, CustomerContact, CustomerType  # noqa: E402

PARENT_TYPE_NAME = "Parent Account"


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dedupe_by_store_key(rows: list[dict]) -> tuple[list[dict], list[str]]:
    seen: dict[str, dict] = {}
    warnings = []
    ordered: list[dict] = []
    for row in rows:
        key = row["store_key"].strip()
        if key not in seen:
            seen[key] = row
            ordered.append(row)
            continue
        if seen[key] == row:
            continue  # exact duplicate row, silently drop
        warnings.append(
            f"store_key {key} appears twice with different data - kept the first, "
            f"review manually: {seen[key]} vs {row}"
        )
    return ordered, warnings


def find_name_collisions(rows: list[dict]) -> list[str]:
    by_name = defaultdict(list)
    for row in rows:
        by_name[row["customer_name"].strip()].append(row["store_key"].strip())
    return [
        f'"{name}" appears under store_keys {keys}'
        for name, keys in by_name.items()
        if len(keys) > 1
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path")
    parser.add_argument("--dry-run", action="store_true", help="Report counts, write nothing")
    args = parser.parse_args()

    raw_rows = load_rows(args.csv_path)
    rows, dupe_warnings = dedupe_by_store_key(raw_rows)
    name_collisions = find_name_collisions(rows)

    banner_names = []
    seen_banners = set()
    for row in rows:
        banner = clean(row["notes"])
        if banner and banner not in seen_banners:
            seen_banners.add(banner)
            banner_names.append(banner)

    with session_scope() as session:
        parent_type = session.scalar(
            select(CustomerType).where(CustomerType.name == PARENT_TYPE_NAME)
        )
        if parent_type is None:
            print(f'No customer_type named "{PARENT_TYPE_NAME}" found - aborting.')
            return

        banner_to_customer_id: dict[str, int] = {}
        parents_created = 0
        for banner in banner_names:
            existing = session.scalar(
                select(Customer).where(
                    Customer.customer_name == banner,
                    Customer.customer_type_id == parent_type.customer_type_id,
                )
            )
            if existing:
                banner_to_customer_id[banner] = existing.customer_id
                continue
            parent = Customer(
                customer_name=banner,
                customer_type_id=parent_type.customer_type_id,
            )
            session.add(parent)
            session.flush()
            banner_to_customer_id[banner] = parent.customer_id
            parents_created += 1

        customers_created = 0
        customers_updated = 0
        store_key_to_customer_id: dict[int, int] = {}
        for row in rows:
            store_key = int(row["store_key"])
            type_id_raw = clean(row["customer_type_id"])
            banner = clean(row["notes"])

            fields = dict(
                customer_name=row["customer_name"].strip(),
                customer_type_id=int(type_id_raw) if type_id_raw else None,
                notes=banner,
                billing_address_line1=clean(row["billing_address_line1"]),
                billing_city=clean(row["billing_city"]),
                billing_state=clean(row["billing_state"]),
                billing_postal_code=clean(row["billing_postal_code"]),
                parent_id=banner_to_customer_id.get(banner) if banner else None,
            )

            existing = session.scalar(select(Customer).where(Customer.store_key == store_key))
            if existing:
                for key, value in fields.items():
                    setattr(existing, key, value)
                store_key_to_customer_id[store_key] = existing.customer_id
                customers_updated += 1
            else:
                customer = Customer(store_key=store_key, **fields)
                session.add(customer)
                session.flush()
                store_key_to_customer_id[store_key] = customer.customer_id
                customers_created += 1

        contacts_created = 0
        for row in rows:
            contact_name = clean(row.get("Contact Name"))
            if not contact_name:
                continue
            customer_id = store_key_to_customer_id[int(row["store_key"])]
            existing = session.scalar(
                select(CustomerContact).where(
                    CustomerContact.customer_id == customer_id,
                    CustomerContact.contact_name == contact_name,
                )
            )
            if existing:
                continue
            session.add(CustomerContact(customer_id=customer_id, contact_name=contact_name))
            contacts_created += 1

        print(f"Rows in CSV: {len(raw_rows)}")
        print(f"Rows after dropping exact duplicates: {len(rows)}")
        print(f"Banner parents created: {parents_created} (of {len(banner_names)} distinct banners)")
        print(f"Stores created: {customers_created}")
        print(f"Stores updated (matched existing store_key): {customers_updated}")
        print(f"Contacts created: {contacts_created}")

        if dupe_warnings:
            print(f"\n{len(dupe_warnings)} store_key conflicts (kept first, please review):")
            for w in dupe_warnings:
                print(f"  - {w}")

        if name_collisions:
            print(f"\n{len(name_collisions)} customer names appear under multiple store_keys (not merged, review manually):")
            for c in name_collisions:
                print(f"  - {c}")

        if args.dry_run:
            session.rollback()
            print("\nDry run - nothing was written.")
        else:
            session.commit()
            print("\nCommitted.")


if __name__ == "__main__":
    main()
