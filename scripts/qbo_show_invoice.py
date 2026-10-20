"""Show how QuickBooks describes one invoice - in particular its custom fields
(where the "PO Reference no." value lives) - so the app can be pointed at the
right field.

Usage:
    python scripts/qbo_show_invoice.py 1038            # by invoice number
    python scripts/qbo_show_invoice.py 1038 --all      # print the whole invoice

Fill in the PO Reference no. on that invoice in QuickBooks first (and save),
then run this. It prints the invoice's CustomField list as QuickBooks returns
it, both as a normal request and asking for all custom fields
(include=enhancedAllCustomFields), plus the custom fields listed in the sales
form settings. Nothing is changed in QuickBooks.

Run where DATABASE_URL and the QBO_* settings in .env are set.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.services import quickbooks as qbo  # noqa: E402


def fetch(session, doc_number: str, enhanced: bool) -> list[dict]:
    params = {
        "query": f"select * from Invoice where DocNumber = '{qbo.escape_literal(doc_number)}' "
        "STARTPOSITION 1 MAXRESULTS 5"
    }
    if enhanced:
        params["include"] = "enhancedAllCustomFields"
    data = qbo._request(session, "GET", "query", params=params)
    return data.get("QueryResponse", {}).get("Invoice", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("doc_number", help="the invoice number shown in QuickBooks, e.g. 1038")
    parser.add_argument("--all", action="store_true", help="print the whole invoice as JSON")
    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    session = sessionmaker(bind=create_engine(normalize_database_url(url)))()
    try:
        for label, enhanced in (("normal request", False), ("with include=enhancedAllCustomFields", True)):
            invoices = fetch(session, args.doc_number, enhanced)
            print(f"\n=== Invoice {args.doc_number}: {label} ===")
            if not invoices:
                print("No invoice with that number was found.")
                continue
            invoice = invoices[0]
            print("CustomField:")
            print(json.dumps(invoice.get("CustomField", []), indent=2))
            for key in ("PONumber", "PrivateNote", "CustomerMemo", "ShipDate", "TrackingNum"):
                if key in invoice:
                    print(f"{key}: {json.dumps(invoice[key])}")
            if args.all:
                print(json.dumps(invoice, indent=2))
        print("\n=== Sales form settings: custom fields ===")
        try:
            prefs = qbo._request(session, "GET", "preferences").get("Preferences", {})
            print(json.dumps((prefs.get("SalesFormsPrefs") or {}).get("CustomField"), indent=2))
        except qbo.QuickBooksError as exc:
            print(f"(couldn't read the settings: {exc})")
    except (qbo.QuickBooksNotConfigured, qbo.QuickBooksNotConnected, qbo.QuickBooksError) as exc:
        sys.exit(str(exc))
    finally:
        session.close()


if __name__ == "__main__":
    main()
