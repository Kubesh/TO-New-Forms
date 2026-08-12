import html
from decimal import Decimal

import streamlit as st

from src.db import session_scope
from src.services.purchase_orders import (
    count_purchase_orders,
    get_po_line_item_stats,
    get_purchase_order,
    search_purchase_orders,
)

PAGE_SIZE = 25

ORDER_TYPE_BADGE_CLASSES = {
    "direct": "po-badge-direct",
    "faire order": "po-badge-faire",
    "distributor": "po-badge-distributor",
}

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
    margin-bottom: 0.6rem;
}
.po-card {
    border: 1px solid rgba(128, 128, 128, 0.35);
    border-radius: 0.5rem;
    padding: 0.85rem 1.25rem;
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
.po-table-header,
.po-row-grid {
    display: grid;
    grid-template-columns: 110px 150px 1fr 100px 100px 140px;
    gap: 0.75rem;
    align-items: center;
}
.po-table-header {
    padding: 0 1.25rem;
    margin-bottom: 0.4rem;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    opacity: 0.55;
}
.po-row-number {
    font-weight: 700;
}
.po-row-type-cell {
    display: flex;
    gap: 0.4rem;
    align-items: center;
    flex-wrap: wrap;
}
.po-badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    background: rgba(128, 128, 128, 0.18);
    color: inherit;
}
.po-badge-direct {
    background: rgba(37, 99, 235, 0.16);
    color: #2563eb !important;
}
.po-badge-faire {
    background: rgba(219, 39, 119, 0.16);
    color: #db2777 !important;
}
.po-badge-distributor {
    background: rgba(234, 88, 12, 0.16);
    color: #ea580c !important;
}
.po-badge-voided {
    background: rgba(185, 28, 28, 0.2);
    color: #b91c1c !important;
}
</style>
"""


def _order_type_badge_html(order_type: str | None) -> str:
    if not order_type:
        return ""
    css_class = ORDER_TYPE_BADGE_CLASSES.get(order_type.strip().lower(), "")
    return f'<span class="po-badge {css_class}">{html.escape(order_type)}</span>'


def _format_quantity(value) -> str:
    if value is None:
        return "0"
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    value = value.normalize()
    if value == value.to_integral_value():
        return str(int(value))
    return str(value)


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
                stats = get_po_line_item_stats(session, [po.po_id for po in purchase_orders])
            else:
                purchase_orders = []
                stats = {}
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not purchase_orders:
        st.info("No purchase orders found.")
        return

    render_po_table(purchase_orders, stats)

    _render_pagination(page, total_pages, total)


def _render_pagination(page: int, total_pages: int, total: int) -> None:
    start = (page - 1) * PAGE_SIZE + 1
    end = min(page * PAGE_SIZE, total)
    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("← Previous", disabled=page <= 1, width="stretch", key="po_prev"):
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
            "Next →", disabled=page >= total_pages, width="stretch", key="po_next"
        ):
            st.session_state["po_page"] = page + 1
            st.rerun()


def render_po_table(purchase_orders, stats_by_po_id: dict, href_base: str = "") -> None:
    """Shared PO list markup, used by both the Purchase Orders page and the
    customer detail page's Purchase Orders section, so the two always match.

    href_base is prepended to each row's link - "" for same-page navigation
    (the PO list page itself), "/purchase-orders" for linking in from a
    different page (e.g. the customer detail page).
    """
    header_labels = ["PO Date", "PO Number", "Customer", "Total SKUs", "Total Units", "Order Type"]
    header = (
        '<div class="po-table-header">'
        + "".join(f"<div>{label}</div>" for label in header_labels)
        + "</div>"
    )

    rows_html = "".join(
        _po_row_html(po, stats_by_po_id.get(po.po_id), href_base) for po in purchase_orders
    )
    st.markdown(
        f'{PO_CARD_CSS}{header}<div class="po-card-list">{rows_html}</div>',
        unsafe_allow_html=True,
    )


def _po_row_html(po, stats, href_base: str) -> str:
    number = html.escape(po.po_number)
    total_skus, total_units = stats if stats else (0, None)
    customer_name = html.escape(po.customer.customer_name) if po.customer else "—"

    card_classes = "po-card"
    if po.voided:
        card_classes += " po-card-voided"

    type_cell = [_order_type_badge_html(po.order_type)]
    if po.voided:
        type_cell.append('<span class="po-badge po-badge-voided">Voided</span>')

    row = (
        '<div class="po-row-grid">'
        f'<div>{po.order_date.isoformat() if po.order_date else "—"}</div>'
        f'<div class="po-row-number">{number}</div>'
        f"<div>{customer_name}</div>"
        f"<div>{total_skus}</div>"
        f"<div>{_format_quantity(total_units)}</div>"
        f'<div class="po-row-type-cell">{"".join(type_cell)}</div>'
        "</div>"
    )

    return (
        f'<a class="po-card-link" href="{href_base}?po_id={po.po_id}" target="_self">'
        f'<div class="{card_classes}">{row}</div></a>'
    )


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
    if po.order_type:
        st.markdown(f'{PO_CARD_CSS}{_order_type_badge_html(po.order_type)}', unsafe_allow_html=True)
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
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.write("No line items on file.")
