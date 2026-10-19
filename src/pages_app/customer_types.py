import html

import streamlit as st

from src.db import session_scope
from src.pages_app.categories import CATEGORY_CARD_CSS
from src.pages_app.pricing_editor import render_pricing
from src.services.customers import (
    create_customer_type,
    customer_counts_by_type,
    get_customer_type,
    list_customer_types,
    search_customers,
    update_customer_type,
)

DEFAULT_PARAM = "default"
CUSTOMER_LIST_LIMIT = 200


def customer_types_page() -> None:
    param = st.query_params.get("customer_type_id")
    if param == DEFAULT_PARAM:
        _render_detail(None)
        return
    if param:
        try:
            customer_type_id = int(param)
        except ValueError:
            customer_type_id = None
        if customer_type_id is not None:
            _render_detail(customer_type_id)
            return

    # Clicking the sidebar link re-runs the page but leaves the browser URL
    # as it was, so clear a stale customer_type_id (as the Customers page does).
    st.query_params.clear()
    _render_list()


def _card_html(href: str, name: str, detail: str, accent: str = "#1A1712") -> str:
    return (
        f'<a class="cat-card-link" href="{href}" target="_self">'
        f'<div class="cat-card" style="--cat-color: {accent};">'
        f'<div class="cat-card-name">{html.escape(name)}</div>'
        f'<div class="cat-card-count">{html.escape(detail)}</div>'
        "</div></a>"
    )


def _count_label(count: int) -> str:
    return f"{count} customer{'' if count == 1 else 's'}"


def _render_list() -> None:
    col_title, col_add = st.columns([3, 1])
    with col_title:
        st.title("Customer Types")
    with col_add:
        st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)
        if st.button("Add customer type", width="stretch", key="ct_add"):
            customer_type_dialog()

    try:
        with session_scope() as session:
            types = list_customer_types(session)
            counts = customer_counts_by_type(session)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    cards = [
        _card_html(
            f"?customer_type_id={DEFAULT_PARAM}",
            "Default pricing",
            "used when nothing more specific is set",
            accent="#F4591A",
        )
    ]
    cards += [
        _card_html(
            f"?customer_type_id={t.customer_type_id}",
            t.name,
            _count_label(counts.get(t.customer_type_id, 0)),
        )
        for t in types
    ]
    st.markdown(
        f'{CATEGORY_CARD_CSS}<div class="cat-card-list">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def _render_detail(customer_type_id: int | None) -> None:
    """customer_type_id None is the default-pricing page."""
    customer_type = None
    if customer_type_id is not None:
        try:
            with session_scope() as session:
                customer_type = get_customer_type(session, customer_type_id)
        except RuntimeError as exc:
            st.error(str(exc))
            return
        if customer_type is None:
            st.warning("Customer type not found.")
            if st.button("← Back to list"):
                st.query_params.clear()
                st.rerun()
            return

    col_back, col_edit = st.columns([3, 1])
    with col_back:
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
    if customer_type is not None:
        with col_edit:
            if st.button("Edit customer type", width="stretch"):
                customer_type_dialog(customer_type.customer_type_id)

    if customer_type is None:
        st.header("Default pricing")
        st.caption(
            "Used for a customer when neither they, their parent account, nor their "
            "customer type has a price."
        )
        render_pricing(key="pricing_default")
        return

    st.header(customer_type.name)
    if customer_type.notes:
        st.caption(customer_type.notes)

    tab_pricing, tab_customers = st.tabs(["Pricing", "Customers"])
    with tab_pricing:
        render_pricing(
            customer_type_id=customer_type.customer_type_id,
            key=f"pricing_type_{customer_type.customer_type_id}",
        )
    with tab_customers:
        with session_scope() as session:
            customers = search_customers(
                session,
                customer_type_id=customer_type.customer_type_id,
                limit=CUSTOMER_LIST_LIMIT,
            )
        if not customers:
            st.write("No customers of this type.")
        for customer in customers:
            st.markdown(
                f'<a href="/customers?customer_id={customer.customer_id}" target="_self" '
                f'style="color: inherit; text-decoration: none;">'
                f"<div style='padding: 0.4rem 0; border-bottom: 1px solid rgba(26,23,18,0.12);'>"
                f"<strong>{html.escape(customer.customer_name)}</strong></div></a>",
                unsafe_allow_html=True,
            )
        if len(customers) == CUSTOMER_LIST_LIMIT:
            st.caption(f"Showing the first {CUSTOMER_LIST_LIMIT} customers.")


@st.dialog("Customer type")
def customer_type_dialog(customer_type_id: int | None = None) -> None:
    existing = None
    if customer_type_id is not None:
        with session_scope() as session:
            existing = get_customer_type(session, customer_type_id)
        if existing is None:
            st.error("Customer type not found.")
            return

    prefix = f"ct_{customer_type_id or 'new'}"
    name = st.text_input("Name*", value=existing.name if existing else "", key=f"{prefix}_name")
    notes = st.text_area("Notes", value=existing.notes or "" if existing else "", key=f"{prefix}_notes")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key=f"{prefix}_save"):
            try:
                with session_scope() as session:
                    if existing:
                        update_customer_type(session, customer_type_id, name, notes)
                    else:
                        create_customer_type(session, name, notes)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"{prefix}_cancel"):
            st.rerun()
