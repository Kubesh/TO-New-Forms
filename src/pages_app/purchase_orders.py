import html

import streamlit as st

from src.db import session_scope
from src.services.purchase_orders import (
    count_purchase_orders,
    get_purchase_order,
    search_purchase_orders,
)

PAGE_SIZE = 25

PO_CARD_CSS = """
<style>
.po-card-link,
.po-card-link:visited,
.po-card-link:hover,
.po-card-link * {
    color: inherit !important;
    text-decoration: none !important;
}
.po-card-list {
    padding-top: 0.75rem;
}
.po-card-link {
    display: block;
    margin-bottom: 0.75rem;
}
.po-card {
    border: 1px solid rgba(128, 128, 128, 0.35);
    border-radius: 0.5rem;
    padding: 1rem 1.25rem;
    width: 100%;
    box-sizing: border-box;
    transition: border-color 0.15s ease;
}
.po-card-link:hover .po-card {
    border-color: rgba(128, 128, 128, 0.7);
}
.po-card-voided {
    border-color: #b91c1c;
}
.po-card-link:hover .po-card-voided {
    border-color: #991b1b;
}
.po-card-top {
    display: flex;
    gap: 0.4rem;
    margin-bottom: 0.35rem;
}
.po-card-badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    background: rgba(128, 128, 128, 0.18);
    color: inherit;
}
.po-card-badge-voided {
    background: rgba(185, 28, 28, 0.2);
    color: #b91c1c !important;
}
.po-card-number {
    font-size: 1.25rem;
    font-weight: 700;
}
.po-card-customer {
    margin-top: 0.15rem;
}
.po-card-date {
    margin-top: 0.25rem;
    opacity: 0.85;
}
</style>
"""


def purchase_orders_page() -> None:
    st.title("Purchase Orders")

    po_id_param = st.query_params.get("po_id")
    if po_id_param:
        try:
            po_id = int(po_id_param)
        except ValueError:
            po_id = None
        if po_id is not None:
            _render_detail(po_id)
            return

    _render_list()


def _render_list() -> None:
    query = st.text_input(
        "Search purchase orders",
        placeholder="Search by PO number…",
        label_visibility="collapsed",
    )

    filters_key = query
    if st.session_state.get("po_filters_key") != filters_key:
        st.session_state["po_filters_key"] = filters_key
        st.session_state["po_page"] = 1
    page = st.session_state.get("po_page", 1)

    try:
        with session_scope() as session:
            total = count_purchase_orders(session, query)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(max(page, 1), total_pages)
            st.session_state["po_page"] = page

            if total:
                purchase_orders = search_purchase_orders(
                    session, query, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
                )
            else:
                purchase_orders = []
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not purchase_orders:
        st.info("No purchase orders found.")
        return

    cards_html = "".join(_po_card_html(po) for po in purchase_orders)
    st.markdown(
        f'{PO_CARD_CSS}<div class="po-card-list">{cards_html}</div>',
        unsafe_allow_html=True,
    )

    _render_pagination(page, total_pages, total)


def _render_pagination(page: int, total_pages: int, total: int) -> None:
    start = (page - 1) * PAGE_SIZE + 1
    end = min(page * PAGE_SIZE, total)
    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("← Previous", disabled=page <= 1, use_container_width=True, key="po_prev"):
            st.session_state["po_page"] = page - 1
            st.rerun()
    with col_info:
        st.markdown(
            f'<div style="text-align:center; padding-top: 0.4rem;">'
            f"Showing {start}–{end} of {total} · Page {page} of {total_pages}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button(
            "Next →", disabled=page >= total_pages, use_container_width=True, key="po_next"
        ):
            st.session_state["po_page"] = page + 1
            st.rerun()


def _po_card_html(po) -> str:
    number = html.escape(po.po_number)
    customer_name = html.escape(po.customer.customer_name) if po.customer else "No linked customer"

    card_classes = "po-card"
    if po.voided:
        card_classes += " po-card-voided"

    top_badges = []
    if po.account_type:
        top_badges.append(f'<span class="po-card-badge">{html.escape(po.account_type)}</span>')
    if po.voided:
        top_badges.append('<span class="po-card-badge po-card-badge-voided">Voided</span>')

    parts = [
        f'<a class="po-card-link" href="?po_id={po.po_id}" target="_self">',
        f'<div class="{card_classes}">',
    ]
    if top_badges:
        parts.append(f'<div class="po-card-top">{"".join(top_badges)}</div>')
    parts.append(f'<div class="po-card-number">{number}</div>')
    parts.append(f'<div class="po-card-customer">{customer_name}</div>')
    if po.order_date:
        parts.append(f'<div class="po-card-date">Ordered {po.order_date.isoformat()}</div>')
    parts.append("</div></a>")
    return "".join(parts)


def _render_detail(po_id: int) -> None:
    with session_scope() as session:
        po = get_purchase_order(session, po_id)

    if not po:
        st.warning("Purchase order not found.")
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
        return

    if st.button("← Back to list"):
        st.query_params.clear()
        st.rerun()

    st.header(po.po_number)
    if po.account_type:
        st.caption(po.account_type)
    if po.voided:
        st.badge("Voided", color="red")

    if po.customer:
        customer_name = html.escape(po.customer.customer_name)
        # customers is the default page (app.py), so a hard link has to go to
        # root "/" rather than "/customers" - Streamlit only treats root as a
        # valid cold-navigation entry point for the default page; its own
        # named path shows a spurious "Page not found" toast on direct load
        # even though the page underneath renders correctly.
        st.markdown(
            f'Customer: <a href="/?customer_id={po.customer.customer_id}" target="_self">'
            f"{customer_name}</a>",
            unsafe_allow_html=True,
        )
    else:
        st.write("Customer: not linked")
    if po.store_key is not None:
        st.caption(f"Previous store key: {po.store_key}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.write(f"**Order date:** {po.order_date.isoformat() if po.order_date else 'N/A'}")
    with col2:
        st.write(f"**Due date:** {po.due_date.isoformat() if po.due_date else 'N/A'}")
    with col3:
        st.write(f"**Ship date:** {po.ship_date.isoformat() if po.ship_date else 'N/A'}")

    if po.note:
        st.write(f"**Note:** {po.note}")

    st.subheader("Line items")
    if po.line_items:
        rows = []
        for li in po.line_items:
            rows.append(
                {
                    "SKU": li.sku or (li.item.sku if li.item else ""),
                    "Item": li.item.name if li.item else (li.item_description or ""),
                    "Quantity": float(li.quantity) if li.quantity is not None else None,
                    "Expanded Weight": float(li.expanded_weight)
                    if li.expanded_weight is not None
                    else None,
                    "Box": li.box or "",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.write("No line items on file.")
