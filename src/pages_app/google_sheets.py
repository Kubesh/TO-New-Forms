from datetime import datetime

import streamlit as st

from src.db import session_scope
from src.services.sheet_sync_runs import SHIPPED_FORM_JOB, get_last_run, list_recent_runs

# The sync is scheduled every 5 minutes; allow a couple of misses before
# calling it stale.
STALE_AFTER_MINUTES = 15


def _format_dt(value: datetime | None) -> str:
    return value.strftime("%m/%d/%Y %I:%M:%S %p") if value else "—"


def _ago(value: datetime) -> str:
    seconds = int((datetime.now() - value).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} hr ago"
    return f"{seconds // 86400} days ago"


def google_sheets_page() -> None:
    st.title("Google Sheets")
    st.subheader("Shipped from form")
    st.caption(
        "Marks purchase orders shipped from new Google Form responses. "
        "Runs on a schedule outside the app (scripts/sync_shipped_from_form.py)."
    )

    with session_scope() as session:
        last = get_last_run(session, SHIPPED_FORM_JOB)
        runs = list_recent_runs(session, SHIPPED_FORM_JOB)

    if last is None:
        st.info("The sync hasn't run yet.")
        return

    age_minutes = (datetime.now() - last.started_at).total_seconds() / 60
    if last.status == "error":
        st.error(f"Last run failed {_ago(last.started_at)}.")
    elif age_minutes > STALE_AFTER_MINUTES:
        st.warning(f"Last run was {_ago(last.started_at)} - it may have stopped running.")
    else:
        st.success(f"Last run {_ago(last.started_at)}.")

    col_time, col_seen, col_shipped = st.columns(3)
    col_time.metric("Last run", _format_dt(last.started_at))
    col_seen.metric("New responses", last.responses_seen)
    col_shipped.metric("POs shipped", last.pos_shipped)

    st.header("Recent runs")
    st.caption("Runs that found nothing new have no log lines.")
    for run in runs:
        label = (
            f"{_format_dt(run.started_at)} — {run.status} — "
            f"{run.responses_seen} new, {run.pos_shipped} shipped"
        )
        if not run.logs:
            st.write(label)
            continue
        with st.expander(label, expanded=run.status == "error"):
            st.code(
                "\n".join(f"{log.level:<7} {log.message}" for log in run.logs),
                language=None,
            )
