"""SANDBOX ONLY: find out how to write the "PO Reference no." box on an invoice.

QuickBooks' API doesn't document a standard PO field, and invoice 1038 shows no
trace of it in the API even with a value saved. This tries several ways of
writing a marker value to a test invoice, one at a time, and prints what
QuickBooks answers. Then YOU open the invoice in QuickBooks and look at the
PO Reference no. box: whichever marker (PROBE-A, PROBE-B, ...) is in it is the
method that works. QuickBooks often accepts a field it doesn't know and quietly
ignores it, so the screen is the real answer.

Usage:
    python scripts/qbo_probe_po_field.py 1038

It edits only the PO-related fields on that invoice (sparse updates) and refuses
to run against production. Use a throwaway invoice.
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

ATTEMPTS = [
    ("PROBE-A", "PONumber property", {"PONumber": "PROBE-A"}, {}),
    (
        "PROBE-B",
        "custom field, DefinitionId 1",
        {"CustomField": [{"DefinitionId": "1", "Name": "PO Reference no.", "Type": "StringType", "StringValue": "PROBE-B"}]},
        {},
    ),
    (
        "PROBE-C",
        "custom field, DefinitionId 1000000001, enhanced",
        {"CustomField": [{"DefinitionId": "1000000001", "Name": "PO Reference no.", "Type": "StringType", "StringValue": "PROBE-C"}]},
        {"include": "enhancedAllCustomFields"},
    ),
    (
        "PROBE-D",
        "custom field by name only",
        {"CustomField": [{"Name": "PO Reference no.", "Type": "StringType", "StringValue": "PROBE-D"}]},
        {},
    ),
    ("PROBE-E", "PONumber, older minor version", {"PONumber": "PROBE-E"}, {"minorversion": "65"}),
    ("PROBE-F", "PONumber, newer minor version 76", {"PONumber": "PROBE-F"}, {"minorversion": "76"}),
    ("PROBE-G", "PONumber, newer minor version 80", {"PONumber": "PROBE-G"}, {"minorversion": "80"}),
]


def read_invoice(session, doc_number):
    data = qbo._request(
        session,
        "GET",
        "query",
        params={"query": f"select * from Invoice where DocNumber = '{qbo.escape_literal(doc_number)}' STARTPOSITION 1 MAXRESULTS 1"},
    )
    invoices = data.get("QueryResponse", {}).get("Invoice", [])
    if not invoices:
        sys.exit(f"No invoice numbered {doc_number}.")
    return invoices[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("doc_number")
    args = parser.parse_args()

    load_dotenv()
    if qbo.environment() != "sandbox":
        sys.exit("Refusing to run: QBO_ENVIRONMENT is not 'sandbox'.")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    session = sessionmaker(bind=create_engine(normalize_database_url(url)))()
    try:
        for marker, label, fields, params in ATTEMPTS:
            invoice = read_invoice(session, args.doc_number)
            body = {"Id": invoice["Id"], "SyncToken": invoice["SyncToken"], "sparse": True, **fields}
            print(f"\n--- {marker}: {label} ---")
            try:
                reply = qbo._request(session, "POST", "invoice", json=body, params=params or None)
            except qbo.QuickBooksError as exc:
                print(f"QuickBooks refused it: {exc}")
                continue
            updated = reply.get("Invoice", {})
            print("accepted. Echoed back:", json.dumps({k: updated.get(k) for k in ("PONumber", "CustomField") if k in updated}))
        print(
            "\nNow open the invoice in QuickBooks, reload it, and look at the PO Reference no. box.\n"
            "Tell me which marker (PROBE-A ... PROBE-G) it shows, or that it's empty."
        )
    except (qbo.QuickBooksNotConfigured, qbo.QuickBooksNotConnected, qbo.QuickBooksError) as exc:
        sys.exit(str(exc))
    finally:
        session.close()


if __name__ == "__main__":
    main()
