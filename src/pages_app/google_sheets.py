from datetime import date, datetime

import streamlit as st

from src.db import session_scope
from src.services.sheet_sync_runs import (
    SHIPPED_FORM_JOB,
    get_last_run,
    list_runs_for_day,
    list_shipments,
    shipped_per_day,
)

# The sync is scheduled every 5 minutes; allow a couple of misses before
# calling it stale.
STALE_AFTER_MINUTES = 15
SHIPMENTS_PAGE_SIZE = 50
OVERVIEW_RANGES = {"Last 14 days": 14, "Last 30 days": 30, "Last 90 days": 90}


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
        "Orders marked shipped using the legacy Google Forms responses. "
        "This script runs on a 5 min schedule outside of the app."
    )

    with session_scope() as session:
        last = get_last_run(session, SHIPPED_FORM_JOB)

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

    tab_overview, tab_detailed, tab_runs = st.tabs(["Overview", "Detailed", "Runs"])
    with tab_overview:
        _render_overview(last)
    with tab_detailed:
        _render_detailed()
    with tab_runs:
        _render_runs()


# --- overview ---------------------------------------------------------------


def _render_overview(last) -> None:
    col_time, col_seen, col_shipped = st.columns(3)
    col_time.metric("Last run", _format_dt(last.started_at))
    col_seen.metric("New responses (last run)", last.responses_seen)
    col_shipped.metric("POs shipped (last run)", last.pos_shipped)

    label = st.selectbox("Range", list(OVERVIEW_RANGES), key="gs_overview_range")
    days = OVERVIEW_RANGES[label]
    with session_scope() as session:
        per_day = shipped_per_day(session, SHIPPED_FORM_JOB, days)

    total = sum(count for _, count in per_day)
    st.metric(f"POs shipped, {label.lower()}", total)
    if total == 0:
        st.caption("Nothing was shipped by the sync in this range.")
        return
    st.bar_chart(
        {"POs shipped": {day: count for day, count in per_day}},
        y_label="POs shipped",
    )
    st.caption("Counted by the day each order shipped (the form's timestamp).")
    st.dataframe(
        [
            {"Date": day.strftime("%a %m/%d/%Y"), "POs shipped": count}
            for day, count in reversed(per_day)
        ],
        hide_index=True,
        width="stretch",
    )


# --- detailed ----------------------------------------------------------------


def _render_detailed() -> None:
    st.caption(
        "Every PO the sync marked shipped. Ship timestamp is the form's submission time, "
        "which becomes the PO's ship date. Marked shipped is when the sync actually did it."
    )
    po_search = st.text_input(
        "Search PO number", placeholder="PO number…", key="gs_detail_search"
    )
    # A new search starts back at page 1.
    if st.session_state.get("gs_detail_search_prev") != po_search:
        st.session_state["gs_detail_search_prev"] = po_search
        st.session_state["gs_detail_page"] = 0
    page = st.session_state.get("gs_detail_page", 0)

    with session_scope() as session:
        shipments, total = list_shipments(
            session, SHIPPED_FORM_JOB, po_search, SHIPMENTS_PAGE_SIZE, page * SHIPMENTS_PAGE_SIZE
        )
    if total == 0:
        st.caption("No shipments found.")
        return
    pages = (total + SHIPMENTS_PAGE_SIZE - 1) // SHIPMENTS_PAGE_SIZE
    if page >= pages:  # the list shrank under us
        st.session_state["gs_detail_page"] = page = pages - 1
        st.rerun()

    st.dataframe(
        [
            {
                "PO Number": s.po_number,
                "Ship timestamp": _format_dt(s.shipped_at),
                "Marked shipped": _format_dt(s.marked_at),
            }
            for s in shipments
        ],
        hide_index=True,
        width="stretch",
    )
    col_prev, col_label, col_next = st.columns([1, 2, 1], vertical_alignment="center")
    with col_prev:
        if st.button("← Previous", disabled=page == 0, width="stretch", key="gs_detail_prev"):
            st.session_state["gs_detail_page"] = page - 1
            st.rerun()
    with col_label:
        st.caption(f"Page {page + 1} of {pages} · {total} shipment{'' if total == 1 else 's'}")
    with col_next:
        if st.button("Next →", disabled=page >= pages - 1, width="stretch", key="gs_detail_next"):
            st.session_state["gs_detail_page"] = page + 1
            st.rerun()


# --- runs --------------------------------------------------------------------


def _hour_label(hour: int) -> str:
    start = datetime(2000, 1, 1, hour)
    return f"{start.strftime('%I:%M %p').lstrip('0')} – {start.strftime('%I').lstrip('0')}:59 {start.strftime('%p')}"


def _set_runs_page(page: int) -> None:
    st.session_state["gs_runs_page"] = page


def _render_runs() -> None:
    st.caption("Pick a date and search to see every run that day and how each one went.")
    day = st.date_input("Date", value=None, format="MM/DD/YYYY", key="gs_runs_date")
    if st.button("Search", type="primary", disabled=day is None, key="gs_runs_search"):
        st.session_state["gs_runs_day"] = day
        st.session_state["gs_runs_page"] = None  # None: open on the latest hour

    searched: date | None = st.session_state.get("gs_runs_day")
    if searched is None:
        return
    with session_scope() as session:
        runs = list_runs_for_day(session, SHIPPED_FORM_JOB, searched)
    if not runs:
        st.info(f"No runs on {searched.strftime('%m/%d/%Y')}.")
        return

    # One page per hour that has runs.
    by_hour: dict[int, list] = {}
    for run in runs:
        by_hour.setdefault(run.started_at.hour, []).append(run)
    hours = sorted(by_hour)
    page = st.session_state.get("gs_runs_page")
    if page is None or not 0 <= page < len(hours):
        page = len(hours) - 1
    hour = hours[page]
    hour_runs = by_hour[hour]

    failed = sum(1 for r in runs if r.status == "error")
    st.write(
        f"**{len(runs)}** run{'' if len(runs) == 1 else 's'} on {searched.strftime('%m/%d/%Y')}"
        + (f", **{failed}** failed" if failed else "")
    )
    col_prev, col_label, col_next = st.columns([1, 2, 1], vertical_alignment="center")
    with col_prev:
        st.button(
            "← Earlier",
            disabled=page == 0,
            width="stretch",
            key="gs_runs_prev",
            on_click=_set_runs_page,
            args=(page - 1,),
        )
    with col_label:
        st.markdown(
            f"**{_hour_label(hour)}**  \n"
            f"<span style='opacity:0.65'>Hour {page + 1} of {len(hours)} with runs · "
            f"{len(hour_runs)} run{'' if len(hour_runs) == 1 else 's'}</span>",
            unsafe_allow_html=True,
        )
    with col_next:
        st.button(
            "Later →",
            disabled=page >= len(hours) - 1,
            width="stretch",
            key="gs_runs_next",
            on_click=_set_runs_page,
            args=(page + 1,),
        )

    for run in reversed(hour_runs):
        duration = (
            f"{(run.finished_at - run.started_at).total_seconds():.0f}s" if run.finished_at else "—"
        )
        label = (
            f"{run.started_at.strftime('%I:%M:%S %p')} — {run.status} — "
            f"{run.responses_seen} new, {run.pos_shipped} shipped · {duration}"
        )
        if not run.logs:
            st.write(label)
            continue
        with st.expander(label, expanded=run.status == "error"):
            st.code(
                "\n".join(f"{log.level:<7} {log.message}" for log in run.logs),
                language=None,
            )
