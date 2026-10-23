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
close (--name-ratio, default 0.85).

Optional, off by default:
  --dominant      also link a conflicted pair that clearly wins: at least 2
                  invoices, and each rival pair is either a single invoice or
                  has at most a third of its count, and is itself outvoted on
                  its other side (so it is a stray, not a real second customer).
                  The losing pairs are reported as strays, never linked.
  --link-review   link the pairs that would only be listed for review, except
                  the app customer ids given in --skip-app-ids. --dry-run changes nothing. --report FILE
writes every pair and its outcome as a CSV; --xlsx FILE writes a workbook with
one sheet per outcome (Linked, Review, Conflict, Skipped) to go through by hand.
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


def dominates(winner, rival) -> bool:
    if rival["count"] == 1:
        return winner["count"] >= 2
    return winner["count"] >= 3 * rival["count"]


def find_strays(pairs, by_qbo, by_app) -> dict:
    """{id(stray pair): winning pair}. A winner outvotes every rival it shares a
    customer with, and each rival is outvoted on its other customer too (or is
    a single invoice), which marks it as a stray rather than a real duplicate."""
    strays: dict = {}
    for winner in pairs:
        rivals = [(c, by_app) for c in by_qbo[winner["qbo_id"]] if c is not winner]
        rivals += [(c, by_qbo) for c in by_app[winner["app_id"]] if c is not winner]
        if not rivals or not all(dominates(winner, c) for c, _ in rivals):
            continue
        orphaned = True
        for rival, other_index in rivals:
            other_key = rival["app_id"] if other_index is by_app else rival["qbo_id"]
            if rival["count"] > 1 and not any(
                d is not rival and d["count"] >= 3 * rival["count"] for d in other_index[other_key]
            ):
                orphaned = False
        if orphaned:
            for rival, _ in rivals:
                strays[id(rival)] = winner
    return strays


def decide(pair, by_qbo, by_app, session, taken, min_matches, min_ratio, strays=(), link_review=False, skip_app_ids=()) -> tuple[str, str]:
    if id(pair) in strays:
        win = strays[id(pair)]
        return "stray", f"outvoted by {win['qbo_name']} -> {win['app_name']} ({win['count']})"
    live = lambda p: p is not pair and id(p) not in strays  # noqa: E731
    others = [p for p in by_qbo[pair["qbo_id"]] if live(p)]
    if others:
        return "conflict", "QuickBooks customer also matches: " + ", ".join(
            f"{p['app_name']} ({p['count']})" for p in others
        )
    others = [p for p in by_app[pair["app_id"]] if live(p)]
    if others:
        return "conflict", "app customer also matches: " + ", ".join(
            f"{p['qbo_name']} ({p['count']})" for p in others
        )
    ratio = name_ratio(pair["qbo_name"], pair["app_name"])
    if pair["count"] < min_matches and ratio < min_ratio:
        if not link_review:
            return "review", f"only {pair['count']} match(es) and names differ (similarity {ratio:.2f})"
        if pair["app_id"] in skip_app_ids:
            return "excluded", f"left out by --skip-app-ids (similarity {ratio:.2f})"
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


XLSX_HEADER = ["QuickBooks customer", "QuickBooks ID", "App customer", "App customer ID",
               "Invoices", "Example POs", "Name similarity", "Outcome", "Detail"]


def report_sheets(results) -> list[tuple[str, list]]:
    """Sheets for the workbook: what was linked, then the things to resolve by hand."""
    conflicts = [r for r in results if r[1] == "conflict"]
    by_app: dict = defaultdict(list)
    by_qbo: dict = defaultdict(list)
    for row in conflicts:
        by_app[row[0]["app_id"]].append(row)
        by_qbo[row[0]["qbo_id"]].append(row)
    two_qb = [r for rows in by_app.values() if len(rows) > 1 for r in rows]
    two_app = [r for rows in by_qbo.values() if len(rows) > 1 for r in rows]
    shown = {id(r[0]) for r in two_qb + two_app}
    other = [r for r in conflicts if id(r[0]) not in shown]
    other += [r for r in results if r[1] in ("review", "excluded", "skipped")]
    return [
        ("Linked", [r for r in results if r[1] in ("link", "already linked")]),
        ("Strays", [r for r in results if r[1] == "stray"]),
        ("2 QB to 1 app", sorted(two_qb, key=lambda r: (r[0]["app_id"], -r[0]["count"]))),
        ("1 QB to 2 app", sorted(two_app, key=lambda r: (r[0]["qbo_id"], -r[0]["count"]))),
        ("Not linked", other),
    ]


def write_xlsx(path, results) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in report_sheets(results):
        sheet = workbook.create_sheet(title)
        sheet.append(XLSX_HEADER)
        if title == "Linked":
            rows = sorted(rows, key=lambda r: _alnum(r[0]["qbo_name"]))
        for pair, outcome, detail in rows:
            sheet.append([
                pair["qbo_name"], pair["qbo_id"], pair["app_name"], pair["app_id"], pair["count"],
                ", ".join(pair["pos"]), round(name_ratio(pair["qbo_name"], pair["app_name"]), 2),
                outcome, detail,
            ])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for index, width in enumerate([38, 14, 44, 14, 10, 38, 16, 14, 70], start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
    workbook.save(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv", help="the report from qbo_match_invoices_to_pos.py")
    parser.add_argument("--dry-run", action="store_true", help="show what would be linked, change nothing")
    parser.add_argument("--min-matches", type=int, default=2, help="invoices needed to link (default 2)")
    parser.add_argument("--name-ratio", type=float, default=0.85, help="name similarity that lets a single match link")
    parser.add_argument("--dominant", action="store_true", help="also link conflicted pairs that clearly win")
    parser.add_argument("--link-review", action="store_true", help="also link the pairs that would be listed for review")
    parser.add_argument("--skip-app-ids", default="", help="comma-separated app customer ids --link-review leaves out")
    parser.add_argument("--report", help="write every pair and its outcome to this CSV file")
    parser.add_argument("--xlsx", help="write a workbook with a sheet per outcome to this file")
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
    strays = find_strays(pairs, by_qbo, by_app) if args.dominant else {}
    skip_app_ids = {int(x) for x in args.skip_app_ids.split(",") if x.strip()}
    taken = {l.qbo_customer_id: cid for cid, l in qbo_sync.customer_links_by_id(session).items()}

    results = []
    for pair in sorted(pairs, key=lambda p: -p["count"]):
        outcome, detail = decide(pair, by_qbo, by_app, session, taken, args.min_matches,
                                 args.name_ratio, strays, args.link_review, skip_app_ids)
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
    for outcome in ("link", "already linked", "stray", "review", "excluded", "conflict", "skipped"):
        group = [(p, d) for p, o, d in results if o == outcome]
        label = verb.get(outcome, outcome.capitalize())
        print(f"\n{label}: {len(group)}")
        if outcome == "already linked":
            continue
        for pair, detail in group:
            line = f"  {pair['qbo_name']}  ->  {pair['app_name']} (id {pair['app_id']}), {pair['count']} invoice(s), PO {', '.join(pair['pos'])}"
            print(line + (f"  [{detail}]" if detail else ""))

    if args.xlsx:
        write_xlsx(args.xlsx, results)
        print(f"\nWrote {args.xlsx}")
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
