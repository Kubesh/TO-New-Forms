"""Connect the app to a QuickBooks Online company (one time), or check on it.

Usage:
    python scripts/qbo_connect.py            # connect
    python scripts/qbo_connect.py --status   # show the connection, test it
    python scripts/qbo_connect.py --make-key # make a QBO_TOKEN_ENCRYPTION_KEY for .env

Needs QBO_CLIENT_ID, QBO_CLIENT_SECRET (and QBO_ENVIRONMENT, QBO_REDIRECT_URI)
in .env, and the redirect URI registered on the Intuit app. To connect:

  1. The script prints a link. Open it, sign in to QuickBooks, pick the
     company, and approve.
  2. QuickBooks sends the browser to the redirect URI. If that's
     http://localhost:8000/callback the page won't load - that's expected.
     Copy the WHOLE address from the browser's address bar (it holds a code
     and the company ID) and paste it back here.

The code in that address works once and for a few minutes only. Run this where
DATABASE_URL points at the database that should hold the connection.
"""
import argparse
import os
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.services import quickbooks as qbo  # noqa: E402


def get_session():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and add your Neon "
            "connection string."
        )
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return sessionmaker(bind=engine)()


def show_status(session) -> None:
    connection = qbo.get_connection(session)
    print(f"Environment: {qbo.environment()}")
    if connection is None:
        print("Not connected. Run: python scripts/qbo_connect.py")
        return
    print(f"Company ID (realm): {connection.realm_id}")
    encrypted = connection.access_token.startswith(qbo.ENCRYPTED_PREFIX)
    print(f"Tokens stored encrypted: {'yes' if encrypted else 'NO (set QBO_TOKEN_ENCRYPTION_KEY)'}")
    print(f"Access token expires:  {connection.access_token_expires_at} UTC")
    print(f"Refresh token expires: {connection.refresh_token_expires_at} UTC")
    info = qbo.company_info(session)
    print(f"Company name: {info.get('CompanyName')}  (country {info.get('Country')})")
    print("Connection works.")


def connect(session) -> None:
    state = qbo.new_state()
    print("1. Open this link, sign in to QuickBooks, choose the company and approve:\n")
    print(qbo.authorize_url(state))
    print(f"\n2. You'll be sent to {qbo.redirect_uri()} - copy the full address from the browser and paste it here.\n")
    pasted = input("Paste the address: ").strip()
    params = parse_qs(urlsplit(pasted).query)
    if "error" in params:
        sys.exit(f"QuickBooks reported: {params['error'][0]}")
    if params.get("state", [""])[0] != state:
        sys.exit("That address doesn't match this connection attempt (state differs) - start again.")
    try:
        code, realm_id = params["code"][0], params["realmId"][0]
    except KeyError:
        sys.exit("The address is missing the code or realmId - copy the whole address after approving.")
    connection = qbo.connect(session, code, realm_id)
    print(f"Connected to company {connection.realm_id} ({qbo.environment()}).")
    info = qbo.company_info(session)
    print(f"Company name: {info.get('CompanyName')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--status", action="store_true", help="show the saved connection and test it")
    parser.add_argument(
        "--make-key", action="store_true", help="print a new QBO_TOKEN_ENCRYPTION_KEY and exit"
    )
    args = parser.parse_args()

    if args.make_key:
        print("Add this line to .env (keep it secret, and don't lose it):\n")
        print(f"QBO_TOKEN_ENCRYPTION_KEY={qbo.generate_encryption_key()}")
        return

    load_dotenv()
    session = get_session()
    try:
        if args.status:
            show_status(session)
        else:
            connect(session)
    except qbo.QuickBooksNotConfigured as exc:
        sys.exit(f"Not configured: {exc}")
    except (qbo.QuickBooksNotConnected, qbo.QuickBooksError) as exc:
        sys.exit(str(exc))
    finally:
        session.close()


if __name__ == "__main__":
    main()
