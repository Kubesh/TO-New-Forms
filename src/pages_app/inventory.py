import html

import streamlit as st

from src.db import session_scope
from src.services.inventory import create_inventory_count, list_inventory

INVENTORY_TABLE_CSS = """
<style>
.inv-row-link,
.inv-row-link:visited,
.inv-row-link:hover,
.inv-row-link * {
    color: inherit !important;
    text-decoration: none !important;
}
.inv-card-list {
    padding-top: 0.75rem;
}
.inv-row-link {
    display: block;
    margin-bottom: 0.6rem;
}
.inv-card {
    border: 2px solid #1A1712;
    border-radius: 0.625rem;
    padding: 0.85rem 1.25rem;
    width: 100%;
    box-sizing: border-box;
    transition: border-color 0.15s ease;
}
.inv-row-link:hover .inv-card {
    border-color: #F4591A;
}
.inv-table-header,
.inv-row-grid {
    display: grid;
    grid-template-columns: 1.2fr 1.2fr 2fr 1fr;
    gap: 0.75rem;
    align-items: center;
}
.inv-table-header {
    padding: 0 1.25rem;
    margin-bottom: 0.4rem;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    opacity: 0.55;
}
.inv-row-item {
    font-weight: 700;
}
@media (max-width: 767px) {
    .inv-table-header {
        display: none;
    }
    .inv-row-grid {
        display: block;
    }
    .inv-row-grid > div {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.75rem;
        padding: 0.35rem 0;
        border-bottom: 1px solid rgba(26, 23, 18, 0.12);
        text-align: right;
    }
    .inv-row-grid > div:last-child {
        border-bottom: none;
    }
    .inv-row-grid > div::before {
        content: attr(data-label);
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        opacity: 0.55;
        text-align: left;
    }
}
</style>
"""


def inventory_page() -> None:
    st.title("Inventory")

    count_mode = st.session_state.get("inventory_count_mode", False)

    col_search, col_toggle = st.columns([3, 1])
    with col_search:
        if count_mode:
            st.caption("Counting every item - use Cancel to go back to search/filter.")
            query = None
        else:
            query = st.text_input(
                "Search inventory",
                placeholder="Search by name or SKU…",
                label_visibility="collapsed",
            )
    with col_toggle:
        if not count_mode:
            if st.button("Count Mode", width="stretch", key="inv_enter_count_mode"):
                st.session_state["inventory_count_mode"] = True
                st.rerun()

    try:
        with session_scope() as session:
            rows = list_inventory(session, query=query)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not rows:
        st.info("No items found.")
        return

    if count_mode:
        _render_count_mode(rows)
    else:
        _render_table(rows)


def _render_table(rows: list) -> None:
    header_labels = ["Category", "Sub Category", "Item", "Current On Hand"]
    header = (
        '<div class="inv-table-header">'
        + "".join(f"<div>{label}</div>" for label in header_labels)
        + "</div>"
    )
    rows_html = "".join(_row_html(item, on_hand) for item, on_hand in rows)
    st.markdown(
        f'{INVENTORY_TABLE_CSS}{header}<div class="inv-card-list">{rows_html}</div>',
        unsafe_allow_html=True,
    )


def _row_html(item, current_on_hand: int | None) -> str:
    category = html.escape(item.category or "—")
    subcategory = html.escape(item.subcategory or "—")
    name = html.escape(item.name)
    on_hand = str(current_on_hand) if current_on_hand is not None else "—"

    row = (
        '<div class="inv-row-grid">'
        f'<div data-label="Category">{category}</div>'
        f'<div data-label="Sub Category">{subcategory}</div>'
        f'<div class="inv-row-item" data-label="Item">{name}</div>'
        f'<div data-label="Current On Hand">{on_hand}</div>'
        "</div>"
    )
    return (
        f'<a class="inv-row-link" href="/items?item_id={item.item_id}" target="_self">'
        f'<div class="inv-card">{row}</div></a>'
    )


def _clear_count_mode_state(rows: list) -> None:
    for item, _ in rows:
        gen = st.session_state.get(f"inv_gen_{item.item_id}", 0)
        st.session_state.pop(f"inv_count_{item.item_id}_{gen}", None)
        st.session_state.pop(f"inv_note_{item.item_id}_{gen}", None)
        st.session_state.pop(f"inv_gen_{item.item_id}", None)
    st.session_state.pop("inv_confirmed_ids", None)


def _render_count_mode(rows: list) -> None:
    confirmed_ids: set[int] = st.session_state.setdefault("inv_confirmed_ids", set())

    header_cols = st.columns([1.2, 1.2, 2, 1, 1, 1.4, 1])
    for col, label in zip(
        header_cols, ["Category", "Sub Category", "Item", "Current", "Counted", "Note", ""]
    ):
        with col:
            st.caption(label)

    highlighted_row_keys = []
    row_keys_by_item: dict[int, tuple[str, str]] = {}
    for item, current_on_hand in rows:
        # The generation suffix lets Revert force a brand-new widget instance
        # (a key Streamlit has never seen) instead of reusing the same key -
        # reusing the same key after popping it from session_state doesn't
        # actually reset what's displayed, because the browser's own copy of
        # the widget's value gets reported straight back to the server on
        # the next interaction (e.g. clicking Save), silently reviving the
        # "cleared" value.
        gen = st.session_state.get(f"inv_gen_{item.item_id}", 0)
        count_key = f"inv_count_{item.item_id}_{gen}"
        note_key = f"inv_note_{item.item_id}_{gen}"
        row_key = f"inv_row_{item.item_id}"
        row_keys_by_item[item.item_id] = (count_key, note_key)
        is_confirmed = item.item_id in confirmed_ids

        counted_value = st.session_state.get(count_key)
        if counted_value is not None:
            highlighted_row_keys.append(row_key)

        with st.container(key=row_key):
            row_cols = st.columns([1.2, 1.2, 2, 1, 1, 1.4, 1])
            with row_cols[0]:
                st.write(item.category or "—")
            with row_cols[1]:
                st.write(item.subcategory or "—")
            with row_cols[2]:
                st.write(item.name)
            with row_cols[3]:
                st.write(str(current_on_hand) if current_on_hand is not None else "—")
            with row_cols[4]:
                st.number_input(
                    "Counted",
                    value=None,
                    min_value=0,
                    step=1,
                    disabled=is_confirmed,
                    key=count_key,
                    label_visibility="collapsed",
                )
            with row_cols[5]:
                st.text_input(
                    "Note",
                    value="",
                    disabled=is_confirmed,
                    key=note_key,
                    label_visibility="collapsed",
                )
            with row_cols[6]:
                check_col, revert_col = st.columns(2)
                with check_col:
                    if st.button(
                        "✓",
                        key=f"inv_check_{item.item_id}",
                        disabled=is_confirmed or counted_value is None,
                        help="Confirm this count",
                        width="stretch",
                    ):
                        confirmed_ids.add(item.item_id)
                        st.rerun()
                with revert_col:
                    if st.button(
                        "↺",
                        key=f"inv_revert_{item.item_id}",
                        help="Clear this row",
                        width="stretch",
                    ):
                        st.session_state.pop(count_key, None)
                        st.session_state.pop(note_key, None)
                        st.session_state[f"inv_gen_{item.item_id}"] = gen + 1
                        confirmed_ids.discard(item.item_id)
                        st.rerun()

    if highlighted_row_keys:
        css_rules = "\n".join(
            f'.st-key-{key} {{ background-color: rgba(250, 204, 21, 0.25); '
            "border-radius: 0.5rem; padding: 0.25rem 0.5rem; }}"
            for key in highlighted_row_keys
        )
        st.markdown(f"<style>{css_rules}</style>", unsafe_allow_html=True)

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="inv_count_save"):
            counts = []
            for item, _ in rows:
                count_key, note_key = row_keys_by_item[item.item_id]
                counted_value = st.session_state.get(count_key)
                if counted_value is not None:
                    counts.append(
                        {
                            "item_id": item.item_id,
                            "counted": int(counted_value),
                            "notes": (st.session_state.get(note_key) or "").strip() or None,
                        }
                    )
            if not counts:
                st.warning("No counts entered yet.")
            else:
                with session_scope() as session:
                    create_inventory_count(session, counts)
                _clear_count_mode_state(rows)
                st.session_state["inventory_count_mode"] = False
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="inv_count_cancel"):
            _clear_count_mode_state(rows)
            st.session_state["inventory_count_mode"] = False
            st.rerun()
