"""Poll ShipStation for labels on orders sent from the app.

Usage:
    python scripts/shipstation_sync.py                 # check once, then exit
    python scripts/shipstation_sync.py --loop 900      # check every 15 minutes
    python scripts/shipstation_sync.py --days 60       # look back further

For every order_shipstation row with no label recorded yet (live POs only:
not voided, no ship date), asks ShipStation whether a label exists and, if
so, records label_created_at / tracking_number / carrier_code on the row.

This does NOT mark the PO shipped. The company prints labels in bulk and
ships days later, and ShipStation's own "shipped" status flips at label
creation, so a label only means "ready to pack" - "Ship PO" in the app stays
a manual step.

Runs as its own process (cron, a scheduler, or --loop under a process
manager) because Streamlit can't receive webhooks. Polling needs no public
URL. ShipStation allows 40 API calls a minute, so calls are spaced out.
"""
import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.db import normalize_database_url  # noqa: E402
from src.services.order_shipstation import list_sends_awaiting_label  # noqa: E402
from src.services.shipstation import (  # noqa: E402
    ShipStationError,
    ShipStationNotConfigured,
    get_labels_for_order,
)

logger = logging.getLogger("shipstation_sync")

# 40 calls/minute is ShipStation's limit; 1.6s apart stays just under it.
SECONDS_BETWEEN_CALLS = 1.6


def get_session():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and add your Neon "
            "connection string."
        )
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return sessionmaker(bind=engine)()


def sync_once(days: int) -> int:
    """Returns the number of rows that got a label recorded."""
    session = get_session()
    updated = 0
    try:
        since = datetime.now() - timedelta(days=days)
        by_order: dict[int, list] = defaultdict(list)
        for send in list_sends_awaiting_label(session, since):
            by_order[send.shipstation_order_id].append(send)

        logger.info("%d ShipStation order(s) awaiting a label", len(by_order))
        for order_id, sends in by_order.items():
            labels = get_labels_for_order(order_id)
            now = datetime.now()
            for send in sends:
                send.last_checked_at = now
            if labels:
                # An order can have several labels (multiple packages); record
                # the earliest one's tracking.
                label = min(labels, key=lambda l: l["label_created_at"] or datetime.max)
                for send in sends:
                    send.label_created_at = label["label_created_at"]
                    send.tracking_number = label["tracking_number"]
                    send.carrier_code = label["carrier_code"]
                    updated += 1
                logger.info("Order %s has a label (tracking %s)", order_id, label["tracking_number"])
            session.commit()
            time.sleep(SECONDS_BETWEEN_CALLS)
    finally:
        session.close()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--loop", type=int, metavar="SECONDS", help="repeat every N seconds")
    parser.add_argument(
        "--days", type=int, default=30, help="only check sends from the last N days (default 30)"
    )
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    while True:
        try:
            updated = sync_once(args.days)
            logger.info("Done - %d row(s) updated", updated)
        except ShipStationNotConfigured as exc:
            logger.error("%s", exc)
            sys.exit(1)
        except ShipStationError as exc:
            # Transient (network, rate limit): in loop mode, try again next round.
            logger.error("%s", exc)
            if not args.loop:
                sys.exit(1)
        if not args.loop:
            return
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
