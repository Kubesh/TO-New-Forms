"""Mark POs as shipped from new Google Form responses.

Usage:
    python scripts/sync_shipped_from_form.py [--since WHEN] [--dry-run]

Reads the tab where the shipping Google Form lands its responses, and for
every response newer than the last one processed, matches the PO number to
po_headers.po_number, ignoring case, spaces and a leading "#". If the PO
exists, isn't voided, and has no ship_date yet, ship_date is set to the form's
submission timestamp. Responses whose PO can't be matched (or matches several),
is voided, or has already shipped are logged and skipped.

Every run (even one that finds nothing) is recorded in sheet_sync_runs with
its log lines in sheet_sync_run_logs, and shown on the app's Google Sheets
page; runs older than 30 days are pruned. The last processed timestamp is
kept in form_sync_state, so run `alembic upgrade head` first. There is no backfill by default: the first run
requires --since so the whole history isn't shipped by accident.
    --since now                 start from the latest response in the sheet
    --since 2026-10-01          process everything from that date on
    --since 2026-10-01T08:00:00 (same, with a time)
After the first run, --since is ignored unless you pass it again to rewind.

Schedule it every 5 minutes, e.g. with cron:
    */5 * * * * cd /path/to/repo && .venv/bin/python scripts/sync_shipped_from_form.py

Env (see .env.example): DATABASE_URL, GOOGLE_SHEETS_CREDENTIALS_FILE,
FORM_RESPONSES_SPREADSHEET_ID (falls back to GOOGLE_SHEETS_SPREADSHEET_ID),
FORM_RESPONSES_TAB_NAME, FORM_TIMESTAMP_HEADER, FORM_PO_NUMBER_HEADER. The
service account only needs view access to the form responses spreadsheet.
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402
from google.oauth2 import service_account  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from src.db import normalize_database_url  # noqa: E402

load_dotenv()

logger = logging.getLogger("sync_shipped_from_form")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
STATE_KEY = "shipped_form_last_timestamp"
JOB = "shipped_from_form"  # matches SHIPPED_FORM_JOB in src/services/sheet_sync_runs.py
LOG_RETENTION_DAYS = 30
SHEETS_EPOCH = datetime(1899, 12, 30)


def read_form_rows() -> list[tuple[datetime, str]]:
    """Returns (submitted_at, po_number) for every response, oldest first."""
    creds_file = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE")
    spreadsheet_id = os.environ.get("FORM_RESPONSES_SPREADSHEET_ID") or os.environ.get(
        "GOOGLE_SHEETS_SPREADSHEET_ID"
    )
    if not creds_file or not spreadsheet_id:
        raise RuntimeError(
            "GOOGLE_SHEETS_CREDENTIALS_FILE and FORM_RESPONSES_SPREADSHEET_ID "
            "(or GOOGLE_SHEETS_SPREADSHEET_ID) must be set."
        )
    tab = os.environ.get("FORM_RESPONSES_TAB_NAME", "Form Responses 1")
    ts_header = os.environ.get("FORM_TIMESTAMP_HEADER", "Timestamp")
    po_header = os.environ.get("FORM_PO_NUMBER_HEADER", "PO Number")

    credentials = service_account.Credentials.from_service_account_file(
        creds_file, scopes=SCOPES
    )
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    # Serial numbers avoid guessing the sheet's locale date format.
    values = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=tab,
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="SERIAL_NUMBER",
        )
        .execute()
        .get("values", [])
    )
    if not values:
        return []

    headers = [str(h).strip() for h in values[0]]
    try:
        ts_col, po_col = headers.index(ts_header), headers.index(po_header)
    except ValueError as exc:
        raise RuntimeError(f"Header not found in {tab!r} ({exc}); have {headers}") from exc

    rows = []
    for row in values[1:]:
        ts = row[ts_col] if len(row) > ts_col else None
        po = row[po_col] if len(row) > po_col else None
        if not isinstance(ts, (int, float)) or po is None or not str(po).strip():
            continue
        submitted_at = (SHEETS_EPOCH + timedelta(days=ts)).replace(microsecond=0)
        rows.append((submitted_at, str(po).strip()))
    rows.sort(key=lambda r: r[0])
    return rows


def parse_since(value: str, rows: list[tuple[datetime, str]]) -> datetime:
    if value == "now":
        return rows[-1][0] if rows else datetime.now().replace(microsecond=0)
    return datetime.fromisoformat(value)


class RunLogCollector(logging.Handler):
    """Keeps this run's log lines so they can be saved with the run row."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[tuple[datetime, str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(
            (datetime.fromtimestamp(record.created), record.levelname, record.getMessage())
        )


def process_responses(conn, args, rows, run_id=None) -> tuple[int, int]:
    """Returns (new responses seen, POs shipped). Raises SystemExit(1) when
    there is no saved position and no --since."""
    stored = conn.execute(
        text("SELECT value FROM form_sync_state WHERE key = :k FOR UPDATE"),
        {"k": STATE_KEY},
    ).scalar()
    if args.since:
        watermark = parse_since(args.since, rows)
    elif stored:
        watermark = datetime.fromisoformat(stored)
    else:
        logger.error("No saved position yet. Re-run with --since now (or a date).")
        raise SystemExit(1)

    new_rows = [r for r in rows if r[0] > watermark]
    shipped = 0
    for submitted_at, po_number in new_rows:
        # Compare with any leading '#' and surrounding spaces ignored, on both sides.
        matches = conn.execute(
            text(
                "SELECT po_id, po_number, ship_date, voided FROM po_headers "
                "WHERE upper(ltrim(trim(po_number), '#')) = upper(:po)"
            ),
            {"po": po_number.strip().lstrip("#").strip()},
        ).all()
        if len(matches) > 1:
            logger.warning(
                "%s: %r matches several POs (%s), skipped",
                submitted_at,
                po_number,
                ", ".join(m.po_number for m in matches),
            )
            continue
        po = matches[0] if matches else None
        if po is None:
            logger.warning("%s: no PO matches %r", submitted_at, po_number)
        elif po.voided:
            logger.warning("%s: PO %s is voided, skipped", submitted_at, po_number)
        elif po.ship_date is not None:
            logger.info("%s: PO %s already shipped, skipped", submitted_at, po_number)
        elif args.dry_run:
            logger.info("%s: would ship PO %s", submitted_at, po_number)
        else:
            # ship_date IS NULL re-checked so a concurrent "Ship PO" click wins.
            result = conn.execute(
                text(
                    "UPDATE po_headers SET ship_date = :ts "
                    "WHERE po_id = :id AND ship_date IS NULL AND NOT voided"
                ),
                {"ts": submitted_at, "id": po.po_id},
            )
            shipped += result.rowcount
            if result.rowcount:
                conn.execute(
                    text(
                        "INSERT INTO sheet_sync_shipments "
                        "(job, run_id, po_id, po_number, shipped_at, marked_at) "
                        "VALUES (:job, :run_id, :po_id, :po_number, :shipped_at, :now)"
                    ),
                    {
                        "job": JOB,
                        "run_id": run_id,
                        "po_id": po.po_id,
                        "po_number": po.po_number,
                        "shipped_at": submitted_at,
                        "now": datetime.now(),
                    },
                )
            logger.info("%s: shipped PO %s", submitted_at, po_number)

    if not args.dry_run:
        new_watermark = new_rows[-1][0] if new_rows else watermark
        conn.execute(
            text(
                "INSERT INTO form_sync_state (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = now()"
            ),
            {"k": STATE_KEY, "v": new_watermark.isoformat()},
        )
    return len(new_rows), shipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--since", help="'now' or an ISO date/datetime to start from")
    parser.add_argument("--dry-run", action="store_true", help="log only, change nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    collector = RunLogCollector()
    logger.addHandler(collector)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set.")
        return 1
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)

    run_id = None
    if not args.dry_run:
        # Own transaction so the run is visible in the app even if it crashes.
        with engine.begin() as conn:
            run_id = conn.execute(
                text(
                    "INSERT INTO sheet_sync_runs (job, started_at) "
                    "VALUES (:job, :now) RETURNING run_id"
                ),
                {"job": JOB, "now": datetime.now()},
            ).scalar()

    status, seen, shipped, exit_code = "ok", 0, 0, 0
    try:
        rows = read_form_rows()
        with engine.begin() as conn:
            seen, shipped = process_responses(conn, args, rows, run_id)
        logger.info("%d new response(s), %d PO(s) shipped", seen, shipped)
    except SystemExit as exc:
        status, exit_code = "error", int(exc.code or 1)
    except Exception:
        logger.exception("Run failed")
        status, exit_code = "error", 1

    if run_id is not None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE sheet_sync_runs SET finished_at = :now, status = :status, "
                    "responses_seen = :seen, pos_shipped = :shipped WHERE run_id = :id"
                ),
                {
                    "now": datetime.now(),
                    "status": status,
                    "seen": seen,
                    "shipped": shipped,
                    "id": run_id,
                },
            )
            # Skip the "N new response(s)" summary on quiet runs; the run row
            # already says so and this keeps the log table small.
            lines = [r for r in collector.records if seen or r[1] != "INFO"]
            if lines:
                conn.execute(
                    text(
                        "INSERT INTO sheet_sync_run_logs (run_id, logged_at, level, message) "
                        "VALUES (:run_id, :at, :level, :message)"
                    ),
                    [
                        {"run_id": run_id, "at": at, "level": level, "message": message}
                        for at, level, message in lines
                    ],
                )
            conn.execute(
                text("DELETE FROM sheet_sync_runs WHERE job = :job AND started_at < :cutoff"),
                {"job": JOB, "cutoff": datetime.now() - timedelta(days=LOG_RETENTION_DAYS)},
            )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
