"""Record past QuickBooks invoices against their POs in the qbo_invoices table.

Usage:
    python scripts/link_qbo_invoices_to_pos.py --dry-run [--report invoices.csv]
    python scripts/link_qbo_invoices_to_pos.py [--since 2024-01-01]

Uses the same matching as qbo_match_invoices_to_pos.py: an invoice is matched
to a PO when its PO number (custom field, private note or customer memo, '#'
stripped, case ignored) equals exactly one PO's number in the app, and no other
invoice carries that number. Duplicates on either side are left alone.

Each clean match becomes a qbo_invoices row for the current QuickBooks company
(status 'created', with the QuickBooks invoice id, number, customer and total),
so the PO shows its invoice in the app and can't be invoiced a second time. The
PO's invoice number is filled in if it was empty.

Skipped, with the reason listed at the end and in --report:
  - the PO already has a live invoice in the app (an existing record is never
    changed, even if it points at a different invoice)
  - the invoice is already recorded against another PO
  - voided invoices
  - the invoice's QuickBooks customer isn't the one the PO's customer is linked
    to (same rule the app uses: the customer's own link, else its parent's).
    An unlinked customer is fine. --ignore-customer turns this check off.

Everything is written in one transaction at the end; --dry-run writes nothing.
Run where DATABASE_URL and the QBO_* settings in .env are set.
"""
import argparse
import csv
import os
import sys
import uuid
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import qbo_match_invoices_to_pos as matcher  # noqa: E402
from src.db import normalize_database_url  # noqa: E402
from src.models import PurchaseOrder, QboInvoice  # noqa: E402
from src.services import qbo_sync  # noqa: E402
from src.services import quickbooks as qbo  # noqa: E402

QBO_ERRORS = (qbo.QuickBooksNotConfigured, qbo.QuickBooksNotConnected, qbo.QuickBooksError)


def is_voided(invoice: dict) -> bool:
    return "void" in (invoice.get("PrivateNote") or "").lower() and not float(invoice.get("TotalAmt") or 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", help="only invoices dated on/after this day (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be recorded, change nothing")
    parser.add_argument("--ignore-customer", action="store_true", help="don't compare QuickBooks and app customers")
    parser.add_argument("--report", help="write one CSV row per matched invoice and its outcome")
    args = parser.parse_args(argv)

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    session = sessionmaker(bind=create_engine(normalize_database_url(url)))()
    try:
        realm = qbo_sync.current_realm(session)
        if realm is None:
            sys.exit("QuickBooks isn't connected - run python scripts/qbo_connect.py first.")
        print("Reading invoices from QuickBooks…", file=sys.stderr)
        invoices = {str(i["Id"]): i for i in matcher.fetch_invoices(session, args.since)}
    except QBO_ERRORS as exc:
        sys.exit(str(exc))

    pos = matcher.load_pos(session)
    rows = [matcher.match_invoice(i, pos, False) for i in invoices.values()]
    matcher.mark_shared_pos(rows)
    matched = [r for r in rows if r["status"] == "matched"]
    print(f"{len(invoices)} invoices read; {len(matched)} match exactly one PO.")

    live_by_po = {
        row.po_id: row
        for row in session.scalars(
            select(QboInvoice).where(QboInvoice.realm_id == realm, QboInvoice.status == "created")
        )
    }
    recorded = {row.qbo_invoice_id: row.po_id for row in live_by_po.values() if row.qbo_invoice_id}

    results = []  # (row, outcome, detail)
    for row in matched:
        invoice = invoices[str(row["invoice_id"])]
        po_id = int(row["po_id"])
        outcome, detail = "record", ""
        existing = live_by_po.get(po_id)
        if is_voided(invoice):
            outcome, detail = "skipped", "voided invoice"
        elif existing is not None:
            if existing.qbo_invoice_id == str(row["invoice_id"]):
                outcome = "already recorded"
            else:
                outcome, detail = "skipped", f"PO already has invoice {existing.doc_number or existing.qbo_invoice_id}"
        elif str(row["invoice_id"]) in recorded:
            outcome, detail = "skipped", f"invoice already recorded against PO id {recorded[str(row['invoice_id'])]}"
        elif not args.ignore_customer:
            po = session.get(PurchaseOrder, po_id)
            if po is not None and po.customer is not None:
                _, link = qbo_sync.invoice_target(session, po.customer)
                if link is not None and link.qbo_customer_id != str(row["qbo_customer_id"]):
                    outcome = "skipped"
                    detail = (
                        f"customer differs: invoice is for {row['qbo_customer_name']}, "
                        f"PO's customer is linked to {link.qbo_display_name}"
                    )
        if outcome == "record":
            live_by_po[po_id] = recorded_row = QboInvoice(
                po_id=po_id,
                realm_id=realm,
                request_id=f"imported-{uuid.uuid4().hex[:24]}",
                status="created",
                qbo_customer_id=str(row["qbo_customer_id"]) if row["qbo_customer_id"] else None,
                qbo_invoice_id=str(row["invoice_id"]),
                doc_number=row["doc_number"],
                total_amount=invoice.get("TotalAmt"),
            )
            recorded[str(row["invoice_id"])] = po_id
            if not args.dry_run:
                session.add(recorded_row)
                po = session.get(PurchaseOrder, po_id)
                if po is not None and row["doc_number"] and not (po.invoice_number or "").strip():
                    po.invoice_number = row["doc_number"]
        results.append((row, outcome, detail))

    if not args.dry_run:
        session.commit()

    counts = Counter(outcome for _, outcome, _ in results)
    verb = "Would record" if args.dry_run else "Recorded"
    print(f"\n{verb} {counts['record']} invoice(s); {counts['already recorded']} were already recorded; "
          f"{counts['skipped']} skipped.")
    skipped = [(r, d) for r, o, d in results if o == "skipped"]
    for reason, n in Counter(" ".join(d.split(":")[0].split()[:4]) for _, d in skipped).most_common():
        print(f"  {n:5}  {reason}")
    if skipped:
        print("\nSkipped:")
        for row, detail in skipped[:100]:
            print(f"  invoice {row['doc_number']} (PO {row['po_number']}): {detail}")
        if len(skipped) > 100:
            print(f"  … and {len(skipped) - 100} more (see --report)")

    if args.report:
        with open(args.report, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["invoice_id", "doc_number", "txn_date", "total", "qbo_customer_name",
                             "po_id", "po_number", "app_customer_name", "outcome", "detail"])
            for row, outcome, detail in results:
                writer.writerow([row["invoice_id"], row["doc_number"], row["txn_date"], row["total"],
                                 row["qbo_customer_name"], row["po_id"], row["po_number"],
                                 row["app_customer_name"], outcome, detail])
        print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
