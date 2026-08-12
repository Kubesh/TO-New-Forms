"""Update customers.phone_number from a store_key/phone_number CSV.

Usage:
    python scripts/update_customer_phone_numbers.py path/to/file.csv [--dry-run]

Expects columns: store_key, phone_number.

Rows with a blank phone_number are skipped entirely - that customer's
phone_number is left untouched, not cleared. Rows whose store_key
doesn't match any customer are reported and skipped.

Safe to re-run: it's a plain update by store_key, not an insert.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.models import Customer  # noqa: E402


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path")
    parser.add_argument("--dry-run", action="store_true", help="Report counts, write nothing")
    args = parser.parse_args()

    raw_rows = load_rows(args.csv_path)
    rows, dupe_warnings = dedupe_by_store_key(raw_rows)

    blank_skipped = 0
    updates: dict[int, str] = {}
    for row in rows:
        phone = clean(row["phone_number"])
        if not phone:
            blank_skipped += 1
            continue
        updates[int(row["store_key"])] = phone

    session = get_session()
    try:
        existing = {
            c.store_key: c
            for c in session.scalars(
                select(Customer).where(Customer.store_key.in_(updates.keys()))
            )
        }

        not_found = []
        changed = 0
        unchanged = 0
        for store_key, phone in updates.items():
            customer = existing.get(store_key)
            if customer is None:
                not_found.append(store_key)
                continue
            if customer.phone_number == phone:
                unchanged += 1
                continue
            customer.phone_number = phone
            changed += 1

        print(f"Rows in CSV: {len(raw_rows)}")
        print(f"Rows after dropping exact duplicates: {len(rows)}")
        print(f"Rows with blank phone (skipped): {blank_skipped}")
        print(f"Customers updated: {changed}")
        print(f"Customers already matching (no-op): {unchanged}")
        print(f"store_keys with no matching customer: {len(not_found)}")

        if not_found:
            print(f"\nUnmatched store_keys (first 20 of {len(not_found)}):")
            for key in not_found[:20]:
                print(f"  - {key}")

        if dupe_warnings:
            print(f"\n{len(dupe_warnings)} store_key conflicts in the CSV (kept first, please review):")
            for w in dupe_warnings:
                print(f"  - {w}")

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
