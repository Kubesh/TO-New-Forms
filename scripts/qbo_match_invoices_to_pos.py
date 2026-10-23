"""Match past QuickBooks invoices to purchase orders by PO number. Read-only.

Usage:
    python scripts/qbo_match_invoices_to_pos.py [--since 2024-01-01] [--report matches.csv]

Pulls every invoice from QuickBooks (all custom fields included), looks at the
text it carries - each custom field, the private note and the customer memo -
and checks whether any of it is a PO number in this app's database. A leading
"#" and surrounding spaces are ignored on both sides, and case doesn't matter;
the whole value has to equal the PO number, so "1234" never matches "12345".

PO numbers aren't unique, so duplicates are ignored rather than guessed at: a
number that more than one PO in the app shares (after the '#' is stripped), or
that more than one invoice carries, is listed but never counted as a match.
Only a PO number that points at exactly one PO and exactly one invoice does.

QuickBooks' API doesn't say where an invoice's PO number lives, so this doesn't
assume: it reports which field each match came from. DocNumber (the invoice
number) is left out unless --include-doc-number is given, because invoice
numbers and PO numbers are both just numbers and match by coincidence.

Prints how many invoices matched exactly one PO, matched several, or matched
none (with samples of what the unmatched values look like), and which fields
the matches came from. --report writes one CSV row per invoice, including the
QuickBooks customer and the app customer of the matched PO, so the next step
(checking they're the same customer) can be done from it. Nothing is changed in
QuickBooks or the database.

Run where DATABASE_URL and the QBO_* settings in .env are set.
"""
import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.models import Customer, PurchaseOrder  # noqa: E402
from src.services import quickbooks as qbo  # noqa: E402

PAGE_SIZE = 1000
ENHANCED_CUSTOM_FIELDS = "enhancedAllCustomFields"


def normalize(value) -> str:
    """The PO number as compared: trimmed, no leading '#', upper case."""
    return str(value or "").strip().lstrip("#").strip().upper()


def fetch_invoices(session, since: str | None) -> list[dict]:
    where = f" where TxnDate >= '{qbo.escape_literal(since)}'" if since else ""
    invoices: list[dict] = []
    start = 1
    while True:
        data = qbo._request(
            session,
            "GET",
            "query",
            params={
                "query": f"select * from Invoice{where} order by Id STARTPOSITION {start} MAXRESULTS {PAGE_SIZE}",
                "include": ENHANCED_CUSTOM_FIELDS,
            },
        )
        page = data.get("QueryResponse", {}).get("Invoice", [])
        invoices.extend(page)
        print(f"  fetched {len(invoices)} invoices…", end="\r", file=sys.stderr)
        if len(page) < PAGE_SIZE:
            print(file=sys.stderr)
            return invoices
        start += PAGE_SIZE


def candidate_values(invoice: dict, include_doc_number: bool) -> list[tuple[str, str]]:
    """(source, text) for every piece of text on the invoice that could be a PO number."""
    found = []
    for field in invoice.get("CustomField") or []:
        value = (field.get("StringValue") or "").strip()
        if value:
            found.append((f"custom field: {field.get('Name') or field.get('DefinitionId')}", value))
    for source, value in (
        ("private note", invoice.get("PrivateNote")),
        ("customer memo", (invoice.get("CustomerMemo") or {}).get("value")),
        ("doc number", invoice.get("DocNumber") if include_doc_number else None),
    ):
        if (value or "").strip():
            found.append((source, value.strip()))
    return found


def load_pos(session) -> dict[str, list[tuple[int, str, Customer | None]]]:
    index: dict[str, list] = defaultdict(list)
    for po in session.scalars(select(PurchaseOrder)):
        index[normalize(po.po_number)].append((po.po_id, po.po_number, po.customer))
    return index


def match_invoice(invoice: dict, pos: dict, include_doc_number: bool) -> dict:
    hits: dict[int, tuple] = {}  # po_id -> (source, raw value, po info), for numbers unique in the app
    duplicate_values: list[str] = []  # values that more than one app PO shares
    candidates = candidate_values(invoice, include_doc_number)
    for source, raw in candidates:
        found = pos.get(normalize(raw), [])
        if len(found) > 1:
            duplicate_values.append(raw)
        elif found:
            hits.setdefault(found[0][0], (source, raw, found[0]))
    ref = invoice.get("CustomerRef") or {}
    if len(hits) == 1:
        status = "matched"
    elif len(hits) > 1:
        status = "several different POs on the invoice"
    elif duplicate_values:
        status = "PO number is shared by several POs in the app"
    else:
        status = "no match"
    row = {
        "invoice_id": invoice.get("Id"),
        "doc_number": invoice.get("DocNumber"),
        "txn_date": invoice.get("TxnDate"),
        "total": invoice.get("TotalAmt"),
        "qbo_customer_id": ref.get("value"),
        "qbo_customer_name": ref.get("name"),
        "values_seen": " | ".join(f"{s}: {v}" for s, v in candidates),
        "source": "",
        "matched_value": "",
        "po_id": "",
        "po_number": "",
        "app_customer_id": "",
        "app_customer_name": "",
        "status": status,
    }
    if len(hits) == 1:
        (po_id, (source, raw, (_, po_number, customer))), = hits.items()
        row.update(
            source=source,
            matched_value=raw,
            po_id=po_id,
            po_number=po_number,
            app_customer_id=customer.customer_id if customer else "",
            app_customer_name=customer.customer_name if customer else "",
        )
    elif hits:
        row["matched_value"] = "; ".join(f"{raw} -> PO {info[1]}" for _, raw, info in hits.values())
    elif duplicate_values:
        row["matched_value"] = "; ".join(duplicate_values)
    return row


def mark_shared_pos(rows: list[dict]) -> int:
    """Invoices that matched the same PO: none of them is a clean 1-to-1 match
    any more. Returns how many POs that affected."""
    by_po: dict = defaultdict(list)
    for row in rows:
        if row["status"] == "matched":
            by_po[row["po_id"]].append(row)
    shared = {po: group for po, group in by_po.items() if len(group) > 1}
    for group in shared.values():
        for row in group:
            row["status"] = "several invoices carry this PO number"
    return len(shared)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", help="only invoices dated on/after this day (YYYY-MM-DD)")
    parser.add_argument("--report", help="write one CSV row per invoice to this file")
    parser.add_argument("--include-doc-number", action="store_true", help="also match the invoice number (noisy)")
    args = parser.parse_args(argv)

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    session = sessionmaker(bind=create_engine(normalize_database_url(url)))()
    try:
        print("Reading invoices from QuickBooks…", file=sys.stderr)
        invoices = fetch_invoices(session, args.since)
    except (qbo.QuickBooksNotConfigured, qbo.QuickBooksNotConnected, qbo.QuickBooksError) as exc:
        sys.exit(str(exc))
    pos = load_pos(session)
    rows = [match_invoice(invoice, pos, args.include_doc_number) for invoice in invoices]
    shared_pos = mark_shared_pos(rows)

    total = len(rows)
    status = Counter(row["status"] for row in rows)
    print(f"\n{total} invoices read; {sum(len(v) for v in pos.values())} POs in the app.")
    if not total:
        return 0

    def pct(n: int) -> str:
        return f"{n} ({n / total:.0%})"

    print(f"  clean matches (one PO, one invoice) : {pct(status['matched'])}")
    ignored = [
        ("several invoices carry this PO number", f"{shared_pos} PO number(s)"),
        ("PO number is shared by several POs in the app", ""),
        ("several different POs on the invoice", ""),
    ]
    for label, extra in ignored:
        if status[label]:
            print(f"  ignored - {label}: {pct(status[label])}" + (f"  [{extra}]" if extra else ""))
    print(f"  no match : {pct(status['no match'])}")

    by_source = Counter(row["source"] for row in rows if row["status"] == "matched")
    if by_source:
        print("\nWhere the clean matches came from:")
        for source, n in by_source.most_common():
            print(f"  {n:5}  {source}")

    no_customer = sum(1 for row in rows if row["status"] == "matched" and not row["app_customer_id"])
    if no_customer:
        print(f"\n{no_customer} matched PO(s) have no customer in the app.")

    unmatched = [row for row in rows if row["status"] == "no match"]
    if unmatched:
        with_values = [row for row in unmatched if row["values_seen"]]
        print(f"\nOf the {len(unmatched)} unmatched, {len(with_values)} carry some text; "
              f"{len(unmatched) - len(with_values)} have no custom field or note text at all.")
        print("Samples of what unmatched invoices carry (invoice number: values):")
        for row in with_values[:15]:
            print(f"  #{row['doc_number']}: {row['values_seen'][:110]}")

    if args.report:
        with open(args.report, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nWrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
