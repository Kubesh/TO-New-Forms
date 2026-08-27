"""Import the item catalog CSV into items.

Usage:
    python scripts/import_items_csv.py path/to/file.csv [--dry-run]

Expects columns: Number/SKU, Item, Category, Subcategory,
Search Terms (separate with commas), Measured In:, Unit Weight (lb),
Sellable Content Weight (lb), Shopify Item #, Shopify Variant #.

Run this before scripts/import_purchase_orders_csv.py - line items are
matched to items by SKU.

Safe to re-run: upserts by sku.
"""
import argparse
import csv
import os
import sys
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.models import Category, Item  # noqa: E402


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


def resolve_category_id(session, cache: dict, category_name: str | None, subcategory_name: str | None):
    """Finds (or creates) the categories row matching this category/
    subcategory pair, returning the most specific one's id - a subcategory
    if given, else the top-level category, else None."""
    if not category_name:
        return None

    top_key = (category_name, None)
    top = cache.get(top_key)
    if top is None:
        top = session.scalars(
            select(Category).where(Category.name == category_name, Category.parent_id.is_(None))
        ).first()
        if top is None:
            top = Category(name=category_name, parent_id=None)
            session.add(top)
            session.flush()
        cache[top_key] = top

    if not subcategory_name:
        return top.category_id

    sub_key = (subcategory_name, top.category_id)
    sub = cache.get(sub_key)
    if sub is None:
        sub = session.scalars(
            select(Category).where(
                Category.name == subcategory_name, Category.parent_id == top.category_id
            )
        ).first()
        if sub is None:
            sub = Category(name=subcategory_name, parent_id=top.category_id)
            session.add(sub)
            session.flush()
        cache[sub_key] = sub
    return sub.category_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path")
    parser.add_argument("--dry-run", action="store_true", help="Report counts, write nothing")
    args = parser.parse_args()

    raw_rows = load_rows(args.csv_path)
    rows = [r for r in raw_rows if clean(r.get("Number/SKU"))]
    skipped_blank = len(raw_rows) - len(rows)

    session = get_session()
    try:
        existing = {
            item.sku: item
            for item in session.scalars(
                select(Item).where(Item.sku.in_([r["Number/SKU"].strip() for r in rows]))
            )
        }

        category_cache: dict = {}
        created = 0
        updated = 0
        for row in rows:
            sku = row["Number/SKU"].strip()
            category_id = resolve_category_id(
                session, category_cache, clean(row.get("Category")), clean(row.get("Subcategory"))
            )
            fields = dict(
                name=clean(row.get("Item")) or sku,
                category_id=category_id,
                search_terms=clean(row.get("Search Terms (separate with commas)")),
                measured_in=clean(row.get("Measured In:")),
                unit_weight_lb=parse_decimal(row.get("Unit Weight (lb)")),
                sellable_content_weight_lb=parse_decimal(row.get("Sellable Content Weight (lb)")),
                shopify_item_number=clean(row.get("Shopify Item #")),
                shopify_variant_number=clean(row.get("Shopify Variant #")),
            )
            item = existing.get(sku)
            if item:
                for key, value in fields.items():
                    setattr(item, key, value)
                updated += 1
            else:
                session.add(Item(sku=sku, **fields))
                created += 1

        print(f"Rows in CSV: {len(raw_rows)}")
        print(f"Rows skipped (no SKU): {skipped_blank}")
        print(f"Items created: {created}")
        print(f"Items updated: {updated}")

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
