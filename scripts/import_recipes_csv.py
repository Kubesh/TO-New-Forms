"""Import a recipe/BOM export into assemblies.

Usage:
    python scripts/import_recipes_csv.py path/to/Recipes.csv [--version-name "Current"]
        [--created-at 2026-01-15] [--dry-run]

Expects columns: Product SKU, Ingredient Number, Amount, Percentage Of Total
(Amount is a "26.20%"-style string - the "%" is stripped and the number is
kept as-is, it isn't re-normalized to sum to 100).

For each distinct Product SKU:
  - Creates an item for the product itself (sku = Product SKU) and for each
    ingredient (sku = Ingredient Number) if one doesn't already exist -
    true insert-ignore: an item that already exists is left untouched, not
    updated. Newly-created items get a placeholder name equal to their SKU
    (there's no descriptive name in this export) - rename them from the
    Items page afterward.
  - Creates one Assembly named after the Product SKU if one doesn't already
    exist.
  - Creates one AssemblyVersion under it (named --version-name, "Current"
    by default) with one AssemblyVersionItem per ingredient row (amount
    negated - consumed) plus one for the product itself (amount = the sum
    of that assembly's ingredient amounts - produced). Skipped if a
    version with that name already exists under the assembly, so this is
    safe to re-run.

--created-at lets you backdate a historical version's created_at (and its
line items') to when that recipe was actually in effect, e.g. when loading
a past version from an archived export rather than the current one.

Safe to re-run: items are insert-ignore, assemblies/versions are skipped
if they already exist by name.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.models import Assembly, AssemblyVersion, AssemblyVersionItem, Item  # noqa: E402


def get_session():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and add your Neon "
            "connection string."
        )
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return sessionmaker(bind=engine)()


def parse_amount(value: str) -> Decimal:
    value = value.strip().rstrip("%")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Couldn't parse amount {value!r}") from exc


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def group_by_product(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sku = row["Product SKU"].strip()
        if sku:
            grouped[sku].append(row)
    return grouped


def get_or_create_item(session, cache: dict, sku: str) -> tuple[Item, bool]:
    """Insert-ignore: returns (item, created) - an item that already exists
    is returned as-is, never modified."""
    if sku in cache:
        return cache[sku], False
    item = session.scalars(select(Item).where(Item.sku == sku)).first()
    created = False
    if item is None:
        item = Item(sku=sku, name=sku)
        session.add(item)
        session.flush()
        created = True
    cache[sku] = item
    return item, created


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv_path")
    parser.add_argument(
        "--version-name",
        default="Current",
        help="Name for the AssemblyVersion created under each assembly (default: Current)",
    )
    parser.add_argument(
        "--created-at",
        default=None,
        help="ISO date/datetime (e.g. 2026-01-15) to backdate this version and its line "
        "items to, instead of the moment the script runs",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report counts, write nothing")
    args = parser.parse_args()

    created_at = None
    if args.created_at:
        created_at = datetime.fromisoformat(args.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

    raw_rows = load_rows(args.csv_path)
    grouped = group_by_product(raw_rows)

    session = get_session()
    try:
        item_cache: dict = {}
        items_created = 0
        assemblies_created = 0
        assemblies_skipped = 0
        versions_created = 0
        versions_skipped = 0
        line_items_created = 0

        for product_sku, rows in sorted(grouped.items()):
            product_item, was_created = get_or_create_item(session, item_cache, product_sku)
            if was_created:
                items_created += 1

            ingredient_amounts: list[tuple[Item, Decimal]] = []
            for row in rows:
                ingredient_sku = row["Ingredient Number"].strip()
                if not ingredient_sku:
                    continue
                ingredient_item, was_created = get_or_create_item(
                    session, item_cache, ingredient_sku
                )
                if was_created:
                    items_created += 1
                ingredient_amounts.append((ingredient_item, parse_amount(row["Amount"])))

            total_amount = sum((amount for _, amount in ingredient_amounts), Decimal("0"))

            assembly = session.scalars(
                select(Assembly).where(Assembly.assembly_name == product_sku)
            ).first()
            if assembly is None:
                assembly = Assembly(assembly_name=product_sku)
                session.add(assembly)
                session.flush()
                assemblies_created += 1
            else:
                assemblies_skipped += 1

            existing_version = session.scalars(
                select(AssemblyVersion).where(
                    AssemblyVersion.assembly_id == assembly.assembly_id,
                    AssemblyVersion.version_name == args.version_name,
                )
            ).first()
            if existing_version is not None:
                versions_skipped += 1
                continue

            version = AssemblyVersion(
                assembly_id=assembly.assembly_id, version_name=args.version_name
            )
            if created_at is not None:
                version.created_at = created_at
                version.updated_at = created_at
            session.add(version)
            session.flush()
            versions_created += 1

            for ingredient_item, amount in ingredient_amounts:
                line_item = AssemblyVersionItem(
                    assembly_version_id=version.assembly_version_id,
                    product_id=ingredient_item.item_id,
                    amount=-amount,
                )
                if created_at is not None:
                    line_item.created_at = created_at
                    line_item.updated_at = created_at
                session.add(line_item)
                line_items_created += 1

            produced_line_item = AssemblyVersionItem(
                assembly_version_id=version.assembly_version_id,
                product_id=product_item.item_id,
                amount=total_amount,
            )
            if created_at is not None:
                produced_line_item.created_at = created_at
                produced_line_item.updated_at = created_at
            session.add(produced_line_item)
            line_items_created += 1

        print(f"Products in CSV: {len(grouped)}")
        print(f"Items created: {items_created}")
        print(f"Assemblies created: {assemblies_created}")
        print(f"Assemblies already existing (reused): {assemblies_skipped}")
        print(f"Versions created ({args.version_name!r}): {versions_created}")
        print(f"Versions already existing (skipped): {versions_skipped}")
        print(f"Assembly version line items created: {line_items_created}")

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
