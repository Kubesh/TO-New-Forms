"""QuickBooks Online (Intuit Accounting API) client: OAuth2 connection, token
upkeep, and queries.

Settings (environment):
  QBO_CLIENT_ID, QBO_CLIENT_SECRET  the app's keys from developer.intuit.com
                                    (the Development keys for the sandbox,
                                    the Production keys for the real company)
  QBO_ENVIRONMENT                   "sandbox" (default) or "production"
  QBO_REDIRECT_URI                  must match one registered on the Intuit
                                    app; defaults to http://localhost:8000/callback

The connection (company ID and tokens) lives in the qbo_connection table and
is created once with scripts/qbo_connect.py. Intuit access tokens last about
an hour and refresh tokens about 100 days, and a refresh hands back a NEW
refresh token, so whichever token set was returned last is the only one that
works: it's saved on every refresh, under a row lock so two processes can't
refresh at once and strand each other.

Functions that take a session may commit it (a refresh saves the new tokens),
so pass one that has no unrelated pending changes.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import QboConnection

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API_BASES = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}
SCOPE = "com.intuit.quickbooks.accounting"
MINOR_VERSION = "75"
REQUEST_TIMEOUT_SECONDS = 30
# Refresh a little early rather than race the expiry.
TOKEN_REFRESH_MARGIN = timedelta(seconds=120)


class QuickBooksNotConfigured(Exception):
    """The QBO_* keys haven't been set."""


class QuickBooksNotConnected(Exception):
    """No (or no longer valid) authorization for the company: run
    scripts/qbo_connect.py. The message is written to be shown as-is."""


class QuickBooksError(Exception):
    """QuickBooks refused the request or couldn't be reached. The message is
    written to be shown as-is."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def environment() -> str:
    value = os.environ.get("QBO_ENVIRONMENT", "sandbox").strip().lower()
    if value not in API_BASES:
        raise QuickBooksNotConfigured(
            f"QBO_ENVIRONMENT is '{value}' - it must be 'sandbox' or 'production'."
        )
    return value


def redirect_uri() -> str:
    return os.environ.get("QBO_REDIRECT_URI", "http://localhost:8000/callback")


def _client_credentials() -> tuple[str, str]:
    client_id = os.environ.get("QBO_CLIENT_ID")
    client_secret = os.environ.get("QBO_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise QuickBooksNotConfigured(
            "QuickBooks isn't set up yet - QBO_CLIENT_ID and QBO_CLIENT_SECRET need to be set."
        )
    return client_id, client_secret


def new_state() -> str:
    return secrets.token_urlsafe(16)


def authorize_url(state: str) -> str:
    """Where the person logs in to QuickBooks and approves the connection."""
    client_id, _ = _client_credentials()
    query = urlencode(
        {
            "client_id": client_id,
            "scope": SCOPE,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def _fault_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    fault = body.get("Fault") or {}
    errors = fault.get("Error") or []
    if errors:
        return "; ".join(
            f"{e.get('Message', '')} {e.get('Detail', '')}".strip() for e in errors
        )
    if "error_description" in body or "error" in body:
        return f"{body.get('error', '')} {body.get('error_description', '')}".strip()
    return response.text[:300]


def _token_request(data: dict) -> dict:
    client_id, client_secret = _client_credentials()
    try:
        response = requests.post(
            TOKEN_URL,
            data=data,
            auth=(client_id, client_secret),
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise QuickBooksError(f"Couldn't reach QuickBooks: {exc}") from exc
    if response.status_code >= 400:
        detail = _fault_message(response)
        if "invalid_grant" in detail:
            raise QuickBooksNotConnected(
                "QuickBooks authorization has expired or was revoked - run "
                "python scripts/qbo_connect.py to connect again."
            )
        raise QuickBooksError(f"QuickBooks token request failed ({response.status_code}): {detail}")
    return response.json()


def _apply_tokens(connection: QboConnection, payload: dict, now: datetime) -> None:
    connection.access_token = payload["access_token"]
    connection.access_token_expires_at = now + timedelta(seconds=int(payload.get("expires_in", 3600)))
    connection.refresh_token = payload["refresh_token"]
    connection.refresh_token_expires_at = now + timedelta(
        seconds=int(payload.get("x_refresh_token_expires_in", 100 * 24 * 3600))
    )


def connect(session: Session, code: str, realm_id: str) -> QboConnection:
    """Exchanges the one-time code from the approval redirect for tokens and
    saves the connection for this company."""
    payload = _token_request(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()}
    )
    env = environment()
    connection = session.scalars(
        select(QboConnection).where(
            QboConnection.environment == env, QboConnection.realm_id == realm_id
        )
    ).first()
    if connection is None:
        connection = QboConnection(environment=env, realm_id=realm_id)
        session.add(connection)
    _apply_tokens(connection, payload, _utcnow())
    session.commit()
    session.refresh(connection)
    return connection


def _current_connection_stmt():
    return (
        select(QboConnection)
        .where(QboConnection.environment == environment())
        .order_by(QboConnection.updated_at.desc(), QboConnection.qbo_connection_id.desc())
        .limit(1)
    )


def get_connection(session: Session) -> QboConnection | None:
    """The connection for the configured environment, if any."""
    return session.scalars(_current_connection_stmt()).first()


def _access_token(session: Session, force_refresh: bool = False) -> tuple[str, str]:
    """(access token, realm id), refreshing the token first if it's expired or
    about to be. Saves the rotated refresh token before returning."""
    connection = session.scalars(_current_connection_stmt().with_for_update()).first()
    if connection is None:
        raise QuickBooksNotConnected(
            "QuickBooks isn't connected yet - run python scripts/qbo_connect.py."
        )
    now = _utcnow()
    token, realm_id = connection.access_token, connection.realm_id
    if not force_refresh and connection.access_token_expires_at - now > TOKEN_REFRESH_MARGIN:
        session.commit()  # nothing changed; just release the row lock
        return token, realm_id
    if connection.refresh_token_expires_at <= now:
        raise QuickBooksNotConnected(
            "The QuickBooks authorization has expired (it lapses after about 100 days "
            "unused) - run python scripts/qbo_connect.py to connect again."
        )
    payload = _token_request(
        {"grant_type": "refresh_token", "refresh_token": connection.refresh_token}
    )
    _apply_tokens(connection, payload, now)
    token = connection.access_token
    session.commit()
    return token, realm_id


def _request(
    session: Session,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    request_id: str | None = None,
) -> dict:
    """One call to the company's API. A 401 gets a single retry after a forced
    token refresh. `request_id` makes a create call safe to retry: QuickBooks
    returns the original result instead of creating a second record."""
    force_refresh = False
    for attempt in (1, 2):
        token, realm_id = _access_token(session, force_refresh=force_refresh)
        query = {"minorversion": MINOR_VERSION, **(params or {})}
        if request_id:
            query["requestid"] = request_id
        url = f"{API_BASES[environment()]}/v3/company/{realm_id}/{path.lstrip('/')}"
        try:
            response = requests.request(
                method,
                url,
                params=query,
                json=json,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise QuickBooksError(f"Couldn't reach QuickBooks: {exc}") from exc
        if response.status_code == 401 and attempt == 1:
            force_refresh = True
            continue
        if response.status_code == 429:
            raise QuickBooksError("QuickBooks rate limit hit - wait a minute and try again.")
        if response.status_code >= 400:
            raise QuickBooksError(
                f"QuickBooks returned {response.status_code}: {_fault_message(response)}"
            )
        return response.json()
    raise QuickBooksNotConnected(  # pragma: no cover - a second 401 returns above
        "QuickBooks rejected the saved authorization - run python scripts/qbo_connect.py."
    )


def escape_literal(value: str) -> str:
    """For putting text inside quotes in a QuickBooks query."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def query(session: Session, sql: str, page_size: int = 1000) -> list[dict]:
    """Runs a QuickBooks query (which has no STARTPOSITION / MAXRESULTS of its
    own) and returns every matching entity, paging through the results."""
    entities: list[dict] = []
    start = 1
    while True:
        data = _request(
            session,
            "GET",
            "query",
            params={"query": f"{sql} STARTPOSITION {start} MAXRESULTS {page_size}"},
        )
        response = data.get("QueryResponse", {})
        page = next((value for value in response.values() if isinstance(value, list)), [])
        entities.extend(page)
        if len(page) < page_size:
            return entities
        start += page_size


def company_info(session: Session) -> dict:
    """The connected company's details (name, country...)."""
    _, realm_id = _access_token(session)
    return _request(session, "GET", f"companyinfo/{realm_id}").get("CompanyInfo", {})


def list_customers(session: Session, include_inactive: bool = False) -> list[dict]:
    where = "" if include_inactive else " where Active = true"
    return query(session, f"select * from Customer{where}")


def list_items(session: Session, include_inactive: bool = False) -> list[dict]:
    where = "" if include_inactive else " where Active = true"
    return query(session, f"select * from Item{where}")
