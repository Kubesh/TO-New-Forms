import html
from decimal import Decimal

import streamlit as st

from src.db import session_scope
from src.services.items import list_item_choices
from src.services.purchase_orders import (
    add_line_item,
    count_purchase_orders,
    get_po_line_item_stats,
    get_purchase_order,
    search_purchase_orders,
    update_line_item_quantities,
    update_purchase_order,
)

ORDER_TYPE_OPTIONS = ["Direct", "Faire Order", "Distributor"]

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

    col_back, col_edit = st.columns([3, 1])
    with col_back:
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
    with col_edit:
        if st.button("Edit purchase order", width="stretch"):
            edit_po_dialog(po.po_id)

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
                    "Original Qty": float(li.original_quantity)
                    if li.original_quantity is not None
                    else None,
                    "Current Qty": float(li.quantity) if li.quantity is not None else None,
                    "Expanded Weight": float(li.expanded_weight)
                    if li.expanded_weight is not None
                    else None,
                    "Box": li.box or "",
                }
            )
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.write("No line items on file.")


@st.dialog("Edit purchase order", width="large")
def edit_po_dialog(po_id: int) -> None:
    with session_scope() as session:
        po = get_purchase_order(session, po_id)
        item_choices = list_item_choices(session)

    if not po:
        st.error("Purchase order not found.")
        return

    has_shipped = po.ship_date is not None
    if has_shipped:
        st.warning(
            f"This PO shipped on {po.ship_date.isoformat()}. Editing a shipped order won't "
            "change what was actually sent - make sure that's really what you want."
        )
        acknowledged = st.checkbox(
            "I understand this PO has already shipped and want to edit it anyway",
            key=f"po_edit_{po_id}_ack",
        )
    else:
        acknowledged = True

    locked = not acknowledged

    type_options = ["No type"] + ORDER_TYPE_OPTIONS
    if po.order_type and po.order_type not in type_options:
        type_options.append(po.order_type)
    current_type = po.order_type or "No type"
    order_type_choice = st.selectbox(
        "Order type",
        type_options,
        index=type_options.index(current_type),
        disabled=locked,
        key=f"po_edit_{po_id}_type",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        order_date = st.date_input(
            "Order date", value=po.order_date, disabled=locked, key=f"po_edit_{po_id}_order_date"
        )
    with col2:
        due_date = st.date_input(
            "Due date", value=po.due_date, disabled=locked, key=f"po_edit_{po_id}_due_date"
        )
    with col3:
        ship_date = st.date_input(
            "Ship date", value=po.ship_date, disabled=locked, key=f"po_edit_{po_id}_ship_date"
        )

    voided = st.checkbox("Voided", value=po.voided, disabled=locked, key=f"po_edit_{po_id}_voided")
    note = st.text_area("Note", value=po.note or "", disabled=locked, key=f"po_edit_{po_id}_note")

    st.markdown("**Line items**")
    st.caption(
        "Quantity can be edited down to zero but items can't be removed. "
        "Original quantity is kept for reference."
    )

    quantity_updates: dict[int, Decimal] = {}
    if po.line_items:
        col_h1, col_h2, col_h3 = st.columns([3, 1, 1])
        with col_h2:
            st.caption("Original qty")
        with col_h3:
            st.caption("Current qty")
        for li in po.line_items:
            row_col1, row_col2, row_col3 = st.columns([3, 1, 1])
            with row_col1:
                label = li.item.name if li.item else (li.item_description or "Unknown item")
                sku_label = li.sku or (li.item.sku if li.item else "")
                st.write(f"{label} ({sku_label})" if sku_label else label)
            with row_col2:
                st.write(_format_quantity(li.original_quantity))
            with row_col3:
                new_qty = st.number_input(
                    "Current qty",
                    min_value=0.0,
                    value=float(li.quantity),
                    step=1.0,
                    disabled=locked,
                    key=f"po_edit_{po_id}_li_{li.line_item_id}",
                    label_visibility="collapsed",
                )
            quantity_updates[li.line_item_id] = Decimal(str(new_qty))
    else:
        st.write("No line items yet.")

    new_row_count_key = f"po_edit_{po_id}_new_row_count"
    new_row_count = st.session_state.get(new_row_count_key, 0)

    if st.button("+ Add item", disabled=locked, key=f"po_edit_{po_id}_add_item"):
        new_row_count += 1
        st.session_state[new_row_count_key] = new_row_count

    item_labels = ["Select an item…"] + [f"{sku} — {name}" for _, sku, name in item_choices]
    item_by_label = {f"{sku} — {name}": (item_id, sku) for item_id, sku, name in item_choices}
    new_rows = []
    for i in range(new_row_count):
        row_col1, row_col2 = st.columns([3, 1])
        with row_col1:
            sku_choice = st.selectbox(
                "New item",
                item_labels,
                disabled=locked,
                key=f"po_edit_{po_id}_new_{i}_sku",
                label_visibility="collapsed",
            )
        with row_col2:
            qty_choice = st.number_input(
                "Qty",
                min_value=0.0,
                value=0.0,
                step=1.0,
                disabled=locked,
                key=f"po_edit_{po_id}_new_{i}_qty",
                label_visibility="collapsed",
            )
        new_rows.append((sku_choice, qty_choice))

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button(
            "Save", type="primary", disabled=locked, width="stretch", key=f"po_edit_{po_id}_save"
        ):
            with session_scope() as session:
                update_purchase_order(
                    session,
                    po_id,
                    order_type=None if order_type_choice == "No type" else order_type_choice,
                    order_date=order_date,
                    due_date=due_date,
                    ship_date=ship_date,
                    voided=voided,
                    note=note.strip() or None,
                )
                update_line_item_quantities(session, quantity_updates)
                for sku_choice, qty_choice in new_rows:
                    if sku_choice == "Select an item…" or qty_choice <= 0:
                        continue
                    item_id, sku = item_by_label[sku_choice]
                    add_line_item(session, po_id, item_id, sku, Decimal(str(qty_choice)))
            st.session_state.pop(new_row_count_key, None)
            st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"po_edit_{po_id}_cancel"):
            st.session_state.pop(new_row_count_key, None)
            st.rerun()
