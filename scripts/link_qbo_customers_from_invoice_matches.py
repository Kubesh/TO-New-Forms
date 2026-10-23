"""Link app customers to QuickBooks customers using the invoice-to-PO matches.

Usage:
    python scripts/qbo_match_invoices_to_pos.py --report matches.csv
    python scripts/link_qbo_customers_from_invoice_matches.py matches.csv --dry-run
    python scripts/link_qbo_customers_from_invoice_matches.py matches.csv

Takes the CSV from qbo_match_invoices_to_pos.py and keeps only the clean rows
(status "matched": one invoice, one PO). For each QuickBooks customer it counts
which app customer its matched POs belong to. A pair is linked only when:
  - every clean match for that QuickBooks customer points at the same app
    customer, and every clean match for that app customer points at the same
    QuickBooks customer (any disagreement is listed as a conflict, not guessed)
  - at least --min-matches invoices back it (default 2): a single match can be
    a PO number that two customers happened to share
  - the app customer isn't already linked (an existing link is never replaced)
    and the QuickBooks customer isn't linked to another app customer

Pairs with fewer matches than --min-matches are listed with a name similarity
so they can be eyeballed; they are linked anyway only if the names are very
close (--name-ratio, default 0.85). --dry-run changes nothing. --report FILE
writes every pair and its outcome as a CSV.
"""
import argparse
import csv
import difflib
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.models import Customer  # noqa: E402
from src.services import qbo_sync  # noqa: E402


def _alnum(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def name_ratio(a, b) -> float:
    # QuickBooks sub-customers are "Parent:Child"; compare the last part too.
    a_last = str(a or "").split(":")[-1]
    return max(
        difflib.SequenceMatcher(None, _alnum(a), _alnum(b)).ratio(),
        difflib.SequenceMatcher(None, _alnum(a_last), _alnum(b)).ratio(),
    )


def load_pairs(path: str) -> list[dict]:
    """One entry per (QuickBooks customer, app customer) seen in clean matches."""
    pairs: dict[tuple, dict] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        needed = {"qbo_customer_id", "qbo_customer_name", "app_customer_id", "app_customer_name", "status"}
        if not needed <= set(reader.fieldnames or []):
            sys.exit(f"The CSV needs these columns: {', '.join(sorted(needed))}.")
        for row in reader:
            if row["status"] != "matched" or not row["app_customer_id"] or not row["qbo_customer_id"]:
                continue
            key = (row["qbo_customer_id"], int(row["app_customer_id"]))
            pair = pairs.setdefault(
                key,
                {
                    "qbo_id": row["qbo_customer_id"],
                    "qbo_name": row["qbo_customer_name"],
                    "app_id": int(row["app_customer_id"]),
                    "app_name": row["app_customer_name"],
                    "count": 0,
                    "pos": [],
                },
            )
            pair["count"] += 1
            if len(pair["pos"]) < 3:
                pair["pos"].append(row["po_number"])
    return list(pairs.values())


def decide(pair, by_qbo, by_app, session, taken, min_matches, min_ratio) -> tuple[str, str]:
    others = [p for p in by_qbo[pair["qbo_id"]] if p is not pair]
    if others:
        return "conflict", "QuickBooks customer also matches: " + ", ".join(
            f"{p['app_name']} ({p['count']})" for p in others
        )
    others = [p for p in by_app[pair["app_id"]] if p is not pair]
    if others:
        return "conflict", "app customer also matches: " + ", ".join(
            f"{p['qbo_name']} ({p['count']})" for p in others
        )
    ratio = name_ratio(pair["qbo_name"], pair["app_name"])
    if pair["count"] < min_matches and ratio < min_ratio:
        return "review", f"only {pair['count']} match(es) and names differ (similarity {ratio:.2f})"
    customer = session.get(Customer, pair["app_id"])
    if customer is None:
        return "skipped", "app customer no longer exists"
    existing = qbo_sync.get_customer_link(session, pair["app_id"])
    if existing is not None:
        if existing.qbo_customer_id == pair["qbo_id"]:
            return "already linked", ""
        return "skipped", f"already linked to a different QuickBooks customer ({existing.qbo_display_name})"
    owner = taken.get(pair["qbo_id"])
    if owner is not None and owner != pair["app_id"]:
        return "skipped", f"that QuickBooks customer is already linked to customer {owner}"
    return "link", ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv", help="the report from qbo_match_invoices_to_pos.py")
    parser.add_argument("--dry-run", action="store_true", help="show what would be linked, change nothing")
    parser.add_argument("--min-matches", type=int, default=2, help="invoices needed to link (default 2)")
    parser.add_argument("--name-ratio", type=float, default=0.85, help="name similarity that lets a single match link")
    parser.add_argument("--report", help="write every pair and its outcome to this CSV file")
    args = parser.parse_args(argv)

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    session = sessionmaker(bind=create_engine(normalize_database_url(url)))()
    pairs = load_pairs(args.csv)

    by_qbo: dict = defaultdict(list)
    by_app: dict = defaultdict(list)
    for pair in pairs:
        by_qbo[pair["qbo_id"]].append(pair)
        by_app[pair["app_id"]].append(pair)
    taken = {l.qbo_customer_id: cid for cid, l in qbo_sync.customer_links_by_id(session).items()}

    results = []
    for pair in sorted(pairs, key=lambda p: -p["count"]):
        outcome, detail = decide(pair, by_qbo, by_app, session, taken, args.min_matches, args.name_ratio)
        if outcome == "link":
            if not args.dry_run:
                try:
                    qbo_sync.link_customer(session, pair["app_id"], pair["qbo_id"], pair["qbo_name"])
                except ValueError as exc:
                    outcome, detail = "skipped", str(exc)
            if outcome == "link":
                taken[pair["qbo_id"]] = pair["app_id"]
        results.append((pair, outcome, detail))

    verb = {"link": "Would link" if args.dry_run else "Linked"}
    for outcome in ("link", "already linked", "review", "conflict", "skipped"):
        group = [(p, d) for p, o, d in results if o == outcome]
        label = verb.get(outcome, outcome.capitalize())
        print(f"\n{label}: {len(group)}")
        if outcome == "already linked":
            continue
        for pair, detail in group:
            line = f"  {pair['qbo_name']}  ->  {pair['app_name']} (id {pair['app_id']}), {pair['count']} invoice(s), PO {', '.join(pair['pos'])}"
            print(line + (f"  [{detail}]" if detail else ""))

    if args.report:
        with open(args.report, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["qbo_customer_id", "qbo_customer_name", "app_customer_id", "app_customer_name",
                             "invoices", "example_pos", "outcome", "detail"])
            for pair, outcome, detail in results:
                writer.writerow([pair["qbo_id"], pair["qbo_name"], pair["app_id"], pair["app_name"],
                                 pair["count"], " ".join(pair["pos"]), outcome, detail])
        print(f"\nWrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
