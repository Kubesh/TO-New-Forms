"""Import a recipe/BOM export into assemblies.

Handles two CSV shapes, auto-detected from the header row:

1. A snapshot export (columns: Product SKU, Ingredient Number, Amount,
   Percentage Of Total) - one row per ingredient in the CURRENT recipe.
   Usage:
       python scripts/import_recipes_csv.py Recipes.csv [--version-name "Current"]
           [--created-at 2026-01-15] [--dry-run]

2. A change-log export (columns: Change Date, Recipe SKU, Base or
   Adjustment Or Future Adjustment, Ingredient SKU, Percent of Recipe,
   Reason for Change) - a full history of every recipe revision.
   Usage:
       python scripts/import_recipes_csv.py ChangeLog.csv [--dry-run]
   Every (Recipe SKU, Change Date, label) group becomes its own
   AssemblyVersion, named "{label} ({date})" and dated to Change Date, with
   Reason for Change carried over as the version's notes. Groups are
   imported exactly as given, including "Base" groups that just restate an
   earlier "Adjustment" - they don't always match exactly (an undocumented
   change can sit between two logged ones), so this doesn't try to dedupe
   them; a faithful copy of the log is safer than a clever-but-wrong guess.
   --version-name/--created-at don't apply to this shape (each version's
   name and date come from its own row) and are rejected if passed.

Both shapes: Amount/Percent values are "26.20%"-style strings - the "%" is
stripped and the number kept as-is, never re-normalized to sum to 100. For
each distinct product/recipe SKU, creates an item for the product itself
and for each ingredient if one doesn't already exist - true insert-ignore,
an item that already exists is left untouched, not updated. Newly-created
items get a placeholder name equal to their SKU (neither export gives a
descriptive name) - rename them from the Items page afterward. Each
version gets one AssemblyVersionItem per ingredient row (amount negated -
consumed) plus one for the product itself (amount = the sum of that
version's ingredient amounts - produced).

Safe to re-run: items are insert-ignore, assemblies/versions are skipped
if they already exist by name under that assembly.
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

SNAPSHOT_COLUMNS = {"Product SKU", "Ingredient Number", "Amount"}
CHANGELOG_COLUMNS = {"Change Date", "Recipe SKU", "Ingredient SKU", "Percent of Recipe"}


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


def detect_format(fieldnames: list[str]) -> str:
    fields = set(fieldnames or [])
    if SNAPSHOT_COLUMNS.issubset(fields):
        return "snapshot"
    if CHANGELOG_COLUMNS.issubset(fields):
        return "changelog"
    raise ValueError(
        f"Unrecognized CSV columns: {fieldnames}\n"
        f"Expected either {sorted(SNAPSHOT_COLUMNS)} (snapshot) "
        f"or {sorted(CHANGELOG_COLUMNS)} (change log)."
    )


class Counters:
    def __init__(self):
        self.items_created = 0
        self.assemblies_created = 0
        self.assemblies_skipped = 0
        self.versions_created = 0
        self.versions_skipped = 0
        self.line_items_created = 0

    def report(self, version_label: str = "versions") -> None:
        print(f"Items created: {self.items_created}")
        print(f"Assemblies created: {self.assemblies_created}")
        print(f"Assemblies already existing (reused): {self.assemblies_skipped}")
        print(f"{version_label} created: {self.versions_created}")
        print(f"{version_label} already existing (skipped): {self.versions_skipped}")
        print(f"Assembly version line items created: {self.line_items_created}")


def get_or_create_item(session, cache: dict, sku: str, counters: Counters) -> Item:
    """Insert-ignore: an item that already exists is returned as-is, never
    modified."""
    if sku in cache:
        return cache[sku]
    item = session.scalars(select(Item).where(Item.sku == sku)).first()
    if item is None:
        item = Item(sku=sku, name=sku)
        session.add(item)
        session.flush()
        counters.items_created += 1
    cache[sku] = item
    return item


def get_or_create_assembly(session, assembly_name: str, counters: Counters) -> Assembly:
    assembly = session.scalars(
        select(Assembly).where(Assembly.assembly_name == assembly_name)
    ).first()
    if assembly is None:
        assembly = Assembly(assembly_name=assembly_name)
        session.add(assembly)
        session.flush()
        counters.assemblies_created += 1
        print(f"  note: created new assembly {assembly_name!r} (not seen before this run)")
    else:
        counters.assemblies_skipped += 1
    return assembly


def create_version_with_items(
    session,
    item_cache: dict,
    counters: Counters,
    assembly: Assembly,
    version_name: str,
    notes: str | None,
    created_at: datetime | None,
    product_sku: str,
    ingredient_rows: list[tuple[str, Decimal]],
) -> None:
    """ingredient_rows: [(ingredient_sku, amount), ...] for this one version.
    Skips creating the version if one with this name already exists under
    the assembly (idempotent re-runs)."""
    existing_version = session.scalars(
        select(AssemblyVersion).where(
            AssemblyVersion.assembly_id == assembly.assembly_id,
            AssemblyVersion.version_name == version_name,
        )
    ).first()
    if existing_version is not None:
        counters.versions_skipped += 1
        return

    version = AssemblyVersion(
        assembly_id=assembly.assembly_id, version_name=version_name, notes=notes
    )
    if created_at is not None:
        version.created_at = created_at
        version.updated_at = created_at
    session.add(version)
    session.flush()
    counters.versions_created += 1

    total_amount = Decimal("0")
    for ingredient_sku, amount in ingredient_rows:
        ingredient_item = get_or_create_item(session, item_cache, ingredient_sku, counters)
        line_item = AssemblyVersionItem(
            assembly_version_id=version.assembly_version_id,
            product_id=ingredient_item.item_id,
            amount=-amount,
        )
        if created_at is not None:
            line_item.created_at = created_at
            line_item.updated_at = created_at
        session.add(line_item)
        counters.line_items_created += 1
        total_amount += amount

    product_item = get_or_create_item(session, item_cache, product_sku, counters)
    produced_line_item = AssemblyVersionItem(
        assembly_version_id=version.assembly_version_id,
        product_id=product_item.item_id,
        amount=total_amount,
    )
    if created_at is not None:
        produced_line_item.created_at = created_at
        produced_line_item.updated_at = created_at
    session.add(produced_line_item)
    counters.line_items_created += 1


def import_snapshot(session, rows: list[dict], args) -> Counters:
    created_at = None
    if args.created_at:
        created_at = datetime.fromisoformat(args.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sku = row["Product SKU"].strip()
        if sku:
            grouped[sku].append(row)

    item_cache: dict = {}
    counters = Counters()
    for product_sku, product_rows in sorted(grouped.items()):
        assembly = get_or_create_assembly(session, product_sku, counters)
        ingredient_rows = [
            (row["Ingredient Number"].strip(), parse_amount(row["Amount"]))
            for row in product_rows
            if row["Ingredient Number"].strip()
        ]
        create_version_with_items(
            session,
            item_cache,
            counters,
            assembly,
            args.version_name,
            None,
            created_at,
            product_sku,
            ingredient_rows,
        )

    print(f"Products in CSV: {len(grouped)}")
    counters.report(f"Versions ({args.version_name!r})")
    return counters


def import_changelog(session, rows: list[dict], args) -> Counters:
    if args.version_name != "Current" or args.created_at:
        print(
            "note: --version-name/--created-at are ignored for a change-log CSV - "
            "each version's name and date come from its own rows.\n"
        )

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    order: list[tuple[str, str, str]] = []
    for row in rows:
        recipe_sku = row["Recipe SKU"].strip()
        change_date = row["Change Date"].strip()
        label = row["Base or Adjustment Or Future Adjustment"].strip()
        if not (recipe_sku and change_date and label):
            continue
        key = (recipe_sku, change_date, label)
        if key not in groups:
            order.append(key)
        groups[key].append(row)

    item_cache: dict = {}
    counters = Counters()
    assembly_cache: dict[str, Assembly] = {}
    for recipe_sku, change_date, label in order:
        group_rows = groups[(recipe_sku, change_date, label)]

        assembly = assembly_cache.get(recipe_sku)
        if assembly is None:
            assembly = get_or_create_assembly(session, recipe_sku, counters)
            assembly_cache[recipe_sku] = assembly

        created_at = datetime.strptime(change_date, "%m/%d/%Y").replace(tzinfo=timezone.utc)
        version_name = f"{label} ({created_at.date().isoformat()})"
        reason = next((r["Reason for Change"].strip() for r in group_rows), None) or None
        ingredient_rows = [
            (row["Ingredient SKU"].strip(), parse_amount(row["Percent of Recipe"]))
            for row in group_rows
            if row["Ingredient SKU"].strip()
        ]

        create_version_with_items(
            session,
            item_cache,
            counters,
            assembly,
            version_name,
            reason,
            created_at,
            recipe_sku,
            ingredient_rows,
        )

    print(f"Change-log groups (recipe + date + label): {len(order)}")
    print(f"Distinct recipes: {len(assembly_cache)}")
    counters.report("Versions")
    return counters


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv_path")
    parser.add_argument(
        "--version-name",
        default="Current",
        help="Snapshot CSVs only: name for the version created under each assembly "
        "(default: Current)",
    )
    parser.add_argument(
        "--created-at",
        default=None,
        help="Snapshot CSVs only: ISO date/datetime (e.g. 2026-01-15) to backdate this "
        "version and its line items to, instead of the moment the script runs",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report counts, write nothing")
    args = parser.parse_args()

    rows = load_rows(args.csv_path)
    csv_format = detect_format(list(rows[0].keys()) if rows else [])
    print(f"Detected format: {csv_format}\n")

    session = get_session()
    try:
        if csv_format == "snapshot":
            import_snapshot(session, rows, args)
        else:
            import_changelog(session, rows, args)

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
