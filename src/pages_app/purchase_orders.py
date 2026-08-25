import html
from datetime import date, timedelta
from decimal import Decimal

import streamlit as st

from src.db import session_scope
from src.services.customers import get_customer, resolve_due_date_days
from src.services.items import list_sellable_item_choices, list_shipping_material_choices
from src.services.order_types import list_order_type_names, resolve_default_order_type
from src.services.purchase_orders import (
    add_line_item,
    count_purchase_orders,
    create_purchase_order,
    delete_purchase_order,
    get_po_line_item_stats,
    get_purchase_order,
    search_purchase_orders,
    update_line_item_quantities,
    update_purchase_order,
)
from src.services.shipping_materials import list_shipping_materials_for_po, replace_shipping_materials

PAGE_SIZE = 25
DEFAULT_NEW_PO_ITEM_ROWS = 5

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
    border: 2px solid #1A1712;
    border-radius: 0.625rem;
    padding: 0.85rem 1.25rem;
    width: 100%;
    box-sizing: border-box;
    transition: border-color 0.15s ease;
}
.po-card-link:hover .po-card {
    border-color: #F4591A;
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
    /* Fixed widths (rather than sizing the PO Number column to its content)
    matter here because each row is its own independent grid - if the
    column sized to content, a row with a longer PO number would end up
    with a wider column than its neighbors, throwing off alignment between
    rows and against the header. 145px comfortably fits the longest PO
    numbers we see without wrapping (paired with nowrap below). */
    grid-template-columns: 95px 145px minmax(120px, 1fr) 75px 75px 120px;
    gap: 0.5rem;
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
    white-space: nowrap;
}
.po-row-type-cell {
    display: flex;
    gap: 0.4rem;
    align-items: center;
    flex-wrap: wrap;
}
@media (max-width: 767px) {
    /* The 6-column grid has no room on a phone screen - stack each PO's
    fields into labeled rows instead (label pulled from data-label via a
    ::before, since the HTML markup is shared with desktop and doesn't
    change). The table header is meaningless once labels are inline. */
    .po-table-header {
        display: none;
    }
    .po-row-grid {
        display: block;
    }
    .po-row-grid > div {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.75rem;
        padding: 0.35rem 0;
        border-bottom: 1px solid rgba(26, 23, 18, 0.12);
        text-align: right;
    }
    .po-row-grid > div:last-child {
        border-bottom: none;
    }
    .po-row-grid > div::before {
        content: attr(data-label);
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        opacity: 0.55;
        text-align: left;
    }
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


def _format_date(value) -> str:
    return value.strftime("%m/%d/%y") if value else "—"


DATE_INPUT_FORMAT = "MM/DD/YYYY"  # Streamlit's date_input only supports 4-digit years


def _format_quantity(value) -> str:
    if value is None:
        return "0"
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    value = value.normalize()
    if value == value.to_integral_value():
        return str(int(value))
    return str(value)


def _item_option_label(sku: str, name: str, subcategory: str | None) -> str:
    # Streamlit's selectbox options are plain text - there's no way to render
    # just the SKU in a lighter color within a single option the way a
    # custom-styled dropdown could.
    if subcategory:
        return f"{sku} — {subcategory}: {name}"
    return f"{sku} — {name}"


def _clear_dialog_state(prefix: str) -> None:
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            del st.session_state[key]


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
        placeholder="Search by PO number or customer name…",
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
        f'<div data-label="PO Date">{_format_date(po.order_date)}</div>'
        f'<div class="po-row-number" data-label="PO Number">{number}</div>'
        f'<div data-label="Customer">{customer_name}</div>'
        f'<div data-label="Total SKUs">{total_skus}</div>'
        f'<div data-label="Total Units">{_format_quantity(total_units)}</div>'
        f'<div class="po-row-type-cell" data-label="Order Type">{"".join(type_cell)}</div>'
        "</div>"
    )

    return (
        f'<a class="po-card-link" href="{href_base}?po_id={po.po_id}" target="_self">'
        f'<div class="{card_classes}">{row}</div></a>'
    )


def _render_detail(po_id: int) -> None:
    with session_scope() as session:
        po = get_purchase_order(session, po_id)
        shipping_materials = list_shipping_materials_for_po(session, po_id) if po else []

    if not po:
        st.warning("Purchase order not found.")
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
        return

    if po.voided:
        col_back, col_edit, col_delete = st.columns([2, 1, 1])
    else:
        col_back, col_edit = st.columns([3, 1])
        col_delete = None
    with col_back:
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
    with col_edit:
        if st.button("Edit purchase order", width="stretch"):
            edit_po_dialog(po.po_id)
    if col_delete is not None:
        with col_delete:
            if st.button("Delete purchase order", width="stretch", key="delete_po_btn"):
                delete_po_confirm_dialog(po.po_id, po.po_number)

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
        st.write(f"**Order date:** {_format_date(po.order_date)}")
    with col2:
        st.write(f"**Due date:** {_format_date(po.due_date)}")
    with col3:
        st.write(f"**Ship date:** {_format_date(po.ship_date)}")

    if po.note:
        st.write(f"**Note:** {po.note}")

    st.subheader("Line items")
    if po.line_items:
        rows = []
        for li in po.line_items:
            rows.append(
                {
                    "SKU": li.sku or (li.item.sku if li.item else ""),
                    "Subcategory": (li.item.subcategory if li.item else None) or "",
                    "Item": li.item.name if li.item else (li.item_description or ""),
                    "Current Quantity": li.quantity,
                }
            )
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.write("No line items on file.")

    col_ship_header, col_ship_btn = st.columns([3, 1])
    with col_ship_header:
        st.subheader("Shipping materials")
    with col_ship_btn:
        if st.button("Manage shipping materials", width="stretch", key="manage_ship_mat_btn"):
            manage_shipping_materials_dialog(po.po_id)
    if shipping_materials:
        rows = [
            {
                "SKU": m.item.sku,
                "Item": m.item.name,
                "Quantity": m.quantity,
            }
            for m in shipping_materials
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.write("No shipping materials recorded.")


@st.dialog("Delete purchase order", width="small")
def delete_po_confirm_dialog(po_id: int, po_number: str) -> None:
    st.warning(f"Delete PO {po_number}? This can't be undone.")
    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button("Delete", type="primary", width="stretch", key=f"po_delete_{po_id}_confirm"):
            with session_scope() as session:
                deleted = delete_purchase_order(session, po_id)
            if deleted:
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Couldn't delete this PO - make sure it's voided and hasn't shipped.")
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"po_delete_{po_id}_cancel"):
            st.rerun()


def _render_new_item_rows(
    key_prefix: str,
    item_choices: list[tuple[int, str, str, str | None]],
    excluded_item_ids: set,
    locked: bool = False,
    default_count: int = 0,
    default_qty: int = 0,
) -> list[tuple[int, str, int]]:
    """Dynamic '+ Add item' rows: an item picker + integer qty each.

    Items already excluded (already on the PO / already recorded) never show
    up in the picker. If the same item is picked in more than one row here,
    the quantities are summed into a single entry rather than inserted
    twice. Returns (item_id, sku, quantity) for rows with a real selection
    and a quantity greater than zero.
    """
    count_key = f"{key_prefix}_new_row_count"
    if count_key not in st.session_state:
        st.session_state[count_key] = default_count
    count = st.session_state[count_key]

    if st.button("+ Add item", disabled=locked, key=f"{key_prefix}_add_item_btn"):
        count += 1
        st.session_state[count_key] = count

    available = [
        (item_id, sku, name, subcategory)
        for item_id, sku, name, subcategory in item_choices
        if item_id not in excluded_item_ids
    ]
    labels = ["Select an item…"] + [_item_option_label(sku, name, subcategory) for _, sku, name, subcategory in available]
    by_label = {
        _item_option_label(sku, name, subcategory): (item_id, sku)
        for item_id, sku, name, subcategory in available
    }

    picks: dict[int, tuple[str, int]] = {}
    for i in range(count):
        row_col1, row_col2 = st.columns([3, 1])
        with row_col1:
            sku_choice = st.selectbox(
                "New item",
                labels,
                disabled=locked,
                key=f"{key_prefix}_new_{i}_sku",
                label_visibility="collapsed",
            )
        with row_col2:
            qty_choice = st.number_input(
                "Qty",
                min_value=0,
                value=default_qty,
                step=1,
                disabled=locked,
                key=f"{key_prefix}_new_{i}_qty",
                label_visibility="collapsed",
            )
        if sku_choice != "Select an item…" and qty_choice > 0:
            item_id, sku = by_label[sku_choice]
            _, existing_qty = picks.get(item_id, (sku, 0))
            picks[item_id] = (sku, existing_qty + qty_choice)

    return [(item_id, sku, qty) for item_id, (sku, qty) in picks.items()]


@st.dialog("Edit purchase order", width="large")
def edit_po_dialog(po_id: int) -> None:
    with session_scope() as session:
        po = get_purchase_order(session, po_id)
        existing_item_ids = {li.item_id for li in po.line_items if li.item_id} if po else set()
        item_choices = list_sellable_item_choices(session, exclude_item_ids=existing_item_ids)
        order_type_options = list_order_type_names(session)

    if not po:
        st.error("Purchase order not found.")
        return

    state_prefix = f"po_edit_{po_id}_"

    has_shipped = po.ship_date is not None
    if has_shipped:
        st.warning(
            f"This PO shipped on {_format_date(po.ship_date)}. Editing a shipped order won't "
            "change what was actually sent - make sure that's really what you want."
        )
        acknowledged = st.checkbox(
            "I understand this PO has already shipped and want to edit it anyway",
            key=f"{state_prefix}ack",
        )
    else:
        acknowledged = True

    locked = not acknowledged

    current_type = po.order_type if po.order_type in order_type_options else resolve_default_order_type(po.customer)
    order_type_choice = st.selectbox(
        "Order type*",
        order_type_options,
        index=order_type_options.index(current_type),
        disabled=locked,
        key=f"{state_prefix}type",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        order_date = st.date_input(
            "Order date",
            value=po.order_date,
            disabled=locked,
            format=DATE_INPUT_FORMAT,
            key=f"{state_prefix}order_date",
        )
    with col2:
        due_date = st.date_input(
            "Due date",
            value=po.due_date,
            disabled=locked,
            format=DATE_INPUT_FORMAT,
            key=f"{state_prefix}due_date",
        )
    with col3:
        ship_date = st.date_input(
            "Ship date",
            value=po.ship_date,
            disabled=locked,
            format=DATE_INPUT_FORMAT,
            key=f"{state_prefix}ship_date",
        )

    voided = st.checkbox("Voided", value=po.voided, disabled=locked, key=f"{state_prefix}voided")
    note = st.text_area("Note", value=po.note or "", disabled=locked, key=f"{state_prefix}note")

    st.markdown("**Line items**")
    st.caption(
        "New quantity can be edited down to zero but items can't be removed. "
        "Original quantity is kept for reference. Rows with an adjusted quantity are "
        "highlighted."
    )

    quantity_updates: dict[int, int] = {}
    highlighted_row_keys: list[str] = []
    if po.line_items:
        header_cols = st.columns([1.1, 1.3, 2.1, 1, 1])
        for col, label in zip(header_cols, ["SKU", "Subcategory", "Item", "Original qty", "New qty"]):
            with col:
                st.caption(label)
        for li in po.line_items:
            qty_key = f"{state_prefix}li_{li.line_item_id}"
            row_key = f"{state_prefix}li_row_{li.line_item_id}"
            current_value = st.session_state.get(qty_key, li.quantity)
            if current_value != li.original_quantity:
                highlighted_row_keys.append(row_key)

            with st.container(key=row_key):
                row_cols = st.columns([1.1, 1.3, 2.1, 1, 1])
                sku_label = li.sku or (li.item.sku if li.item else "")
                subcategory = (li.item.subcategory if li.item else None) or "—"
                item_name = li.item.name if li.item else (li.item_description or "Unknown item")
                with row_cols[0]:
                    st.write(sku_label)
                with row_cols[1]:
                    st.write(subcategory)
                with row_cols[2]:
                    st.write(item_name)
                with row_cols[3]:
                    st.write(str(li.original_quantity))
                with row_cols[4]:
                    new_qty = st.number_input(
                        "New qty",
                        min_value=0,
                        value=int(li.quantity),
                        step=1,
                        disabled=locked,
                        key=qty_key,
                        label_visibility="collapsed",
                    )
            quantity_updates[li.line_item_id] = new_qty
    else:
        st.write("No line items yet.")

    if highlighted_row_keys:
        css_rules = "\n".join(
            f'.st-key-{key} {{ background-color: rgba(250, 204, 21, 0.25); '
            "border-radius: 0.5rem; padding: 0.25rem 0.5rem; }}"
            for key in highlighted_row_keys
        )
        st.markdown(f"<style>{css_rules}</style>", unsafe_allow_html=True)

    new_rows = _render_new_item_rows(
        key_prefix=state_prefix.rstrip("_"),
        item_choices=item_choices,
        excluded_item_ids=existing_item_ids,
        locked=locked,
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button(
            "Save", type="primary", disabled=locked, width="stretch", key=f"{state_prefix}save"
        ):
            with session_scope() as session:
                update_purchase_order(
                    session,
                    po_id,
                    order_type=order_type_choice,
                    order_date=order_date,
                    due_date=due_date,
                    ship_date=ship_date,
                    voided=voided,
                    note=note.strip() or None,
                )
                update_line_item_quantities(session, quantity_updates)
                for item_id, sku, qty in new_rows:
                    add_line_item(session, po_id, item_id, sku, qty)
            _clear_dialog_state(state_prefix)
            st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"{state_prefix}cancel"):
            _clear_dialog_state(state_prefix)
            st.rerun()


@st.dialog("Create purchase order", width="large")
def create_po_dialog(customer_id: int) -> None:
    with session_scope() as session:
        customer = get_customer(session, customer_id)
        item_choices = list_sellable_item_choices(session)
        order_type_options = list_order_type_names(session)

    if not customer:
        st.error("Customer not found.")
        return

    state_prefix = "po_create_"

    st.markdown(
        f'<h4 style="color:#000; margin:0 0 0.5rem 0;">For {html.escape(customer.customer_name)}</h4>',
        unsafe_allow_html=True,
    )

    po_number = st.text_input("PO number*", key=f"{state_prefix}number")

    default_type = resolve_default_order_type(customer)
    default_type_index = (
        order_type_options.index(default_type) if default_type in order_type_options else 0
    )
    order_type_choice = st.selectbox(
        "Order type*", order_type_options, index=default_type_index, key=f"{state_prefix}type"
    )

    default_order_date = date.today()
    default_due_date = default_order_date + timedelta(days=resolve_due_date_days(customer))

    col1, col2, col3 = st.columns(3)
    with col1:
        order_date = st.date_input(
            "Order date",
            value=default_order_date,
            format=DATE_INPUT_FORMAT,
            key=f"{state_prefix}order_date",
        )
    with col2:
        due_date = st.date_input(
            "Due date",
            value=default_due_date,
            format=DATE_INPUT_FORMAT,
            key=f"{state_prefix}due_date",
        )
    with col3:
        ship_date = st.date_input(
            "Ship date", value=None, format=DATE_INPUT_FORMAT, key=f"{state_prefix}ship_date"
        )

    note = st.text_area("Note", value="", key=f"{state_prefix}note")

    st.markdown("**Line items**")
    new_rows = _render_new_item_rows(
        key_prefix=state_prefix.rstrip("_"),
        item_choices=item_choices,
        excluded_item_ids=set(),
        default_count=DEFAULT_NEW_PO_ITEM_ROWS,
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key=f"{state_prefix}save"):
            if not po_number.strip():
                st.error("PO number is required.")
            else:
                try:
                    with session_scope() as session:
                        po = create_purchase_order(
                            session,
                            po_number=po_number.strip(),
                            customer_id=customer_id,
                            order_type=order_type_choice,
                            order_date=order_date,
                            due_date=due_date,
                            ship_date=ship_date,
                            note=note.strip() or None,
                            voided=False,
                        )
                        for item_id, sku, qty in new_rows:
                            add_line_item(session, po.po_id, item_id, sku, qty)
                except Exception:
                    st.error(
                        f"Couldn't create the PO - a purchase order numbered "
                        f"\"{po_number.strip()}\" may already exist."
                    )
                else:
                    _clear_dialog_state(state_prefix)
                    st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"{state_prefix}cancel"):
            _clear_dialog_state(state_prefix)
            st.rerun()


@st.dialog("Manage shipping materials", width="small")
def manage_shipping_materials_dialog(po_id: int) -> None:
    with session_scope() as session:
        po = get_purchase_order(session, po_id)
        materials = list_shipping_materials_for_po(session, po_id)
        existing_item_ids = {m.item_id for m in materials}
        material_choices = list_shipping_material_choices(session)

    if not po:
        st.error("Purchase order not found.")
        return

    state_prefix = f"po_ship_mat_{po_id}_"

    st.caption("Shipping materials can be added or adjusted at any time.")

    quantity_updates: dict[int, int] = {}
    if materials:
        header_cols = st.columns([3, 1])
        with header_cols[1]:
            st.caption("Quantity")
        for m in materials:
            row_col1, row_col2 = st.columns([3, 1])
            with row_col1:
                st.write(f"{m.item.name} ({m.item.sku})")
            with row_col2:
                qty = st.number_input(
                    "Quantity",
                    min_value=0,
                    value=int(m.quantity),
                    step=1,
                    key=f"{state_prefix}{m.order_shipping_material_id}",
                    label_visibility="collapsed",
                )
            quantity_updates[m.item_id] = qty
    else:
        st.write("No shipping materials yet.")

    new_rows = _render_new_item_rows(
        key_prefix=state_prefix.rstrip("_"),
        item_choices=material_choices,
        excluded_item_ids=existing_item_ids,
        default_qty=1,
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key=f"{state_prefix}save"):
            material_entries: dict[int, int] = dict(quantity_updates)
            for item_id, sku, qty in new_rows:
                material_entries[item_id] = material_entries.get(item_id, 0) + qty
            with session_scope() as session:
                replace_shipping_materials(session, po_id, list(material_entries.items()))
            _clear_dialog_state(state_prefix)
            st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"{state_prefix}cancel"):
            _clear_dialog_state(state_prefix)
            st.rerun()
