import html
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

import streamlit as st

from src.db import session_scope
from src.services.categories import subcategory_name
from src.services.customers import get_customer, resolve_due_date_days
from src.services.items import list_sellable_item_choices, list_shipping_material_choices
from src.services import qbo_sync
from src.services import quickbooks as qb
from src.services.order_types import shipstation_block_reason
from src.services.order_shipstation import list_sends_for_po, refresh_labels, send_po
from src.services.order_types import list_order_type_names, resolve_default_order_type
from src.services.pricing import line_amount, order_total
from src.services.po_sheets_sync import SheetLayoutError, remove_line_items, sync_purchase_order
from src.services.purchase_orders import (
    add_line_item,
    price_unpriced_lines,
    count_purchase_orders,
    create_purchase_order,
    delete_purchase_order,
    get_po_line_item_stats,
    get_purchase_order,
    po_ids_sent_to_shipstation,
    search_purchase_orders,
    set_invoice_number,
    ship_purchase_order,
    unship_purchase_order,
    update_line_item_quantities,
    update_purchase_order,
)
from src.services.sheets_sync import SheetsSyncNotConfigured
from src.services.shipping_materials import list_shipping_materials_for_po, replace_shipping_materials
from src.services.shipstation import ShipStationError, ShipStationNotConfigured

logger = logging.getLogger(__name__)

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
.po-card-shipped {
    background: rgba(34, 160, 80, 0.16);
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
    grid-template-columns: 82px minmax(0, 1fr) minmax(0, 1.8fr) 52px 58px 115px 1.4rem 1.4rem;
    gap: 0.5rem;
    align-items: center;
}
.po-table-header > div,
.po-row-grid > div {
    min-width: 0;
}
@media (min-width: 768px) {
    .po-row-grid > div:not(.po-row-type-cell):not(.po-icon-cell) {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
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
.po-icon-cell {
    display: flex;
    align-items: center;
    justify-content: center;
}
@media (max-width: 767px) {
    .po-icon-cell:empty {
        display: none;
    }
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
.po-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.35rem;
    height: 1.35rem;
    border-radius: 999px;
    border: 1.5px solid currentColor;
    font-size: 0.8rem;
    font-weight: 700;
    line-height: 1;
}
.po-icon-invoice {
    color: #15803d !important;
}
.po-icon-label {
    color: #2563eb !important;
    border: none;
    width: 1.5rem;
}
.po-icon svg {
    width: 1.2rem;
    height: 1.2rem;
}
[class*="st-key-porow-"] {
    margin-bottom: -0.15rem;
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


def _format_datetime(value) -> str:
    return value.strftime("%m/%d/%y %-I:%M %p") if value else "—"


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


def _sync_po_to_sheet(po_id: int) -> None:
    """Best-effort: a sync failure shouldn't block saving the PO itself,
    which has already committed by the time this runs."""
    try:
        with session_scope() as session:
            po = get_purchase_order(session, po_id)
            if po is not None:
                sync_purchase_order(po)
    except SheetsSyncNotConfigured:
        pass
    except SheetLayoutError:
        logger.exception("PO sheet layout doesn't match for po_id=%s", po_id)
        st.toast(
            "Saved, but the PO sheet's columns don't match what the app expects, so it "
            "wasn't updated - see the server logs.",
            icon="⚠️",
        )
    except Exception:
        logger.exception("PO sheet sync failed for po_id=%s", po_id)
        st.toast(
            "Saved, but couldn't sync to the PO sheet - check the server logs.",
            icon="⚠️",
        )


def _remove_po_rows_from_sheet(line_item_ids: list[int]) -> None:
    """Best-effort, like _sync_po_to_sheet."""
    try:
        remove_line_items(line_item_ids)
    except SheetsSyncNotConfigured:
        pass
    except Exception:
        logger.exception("PO sheet row removal failed for line items %s", line_item_ids)
        st.toast(
            "Deleted, but couldn't remove its rows from the PO sheet - check the server logs.",
            icon="⚠️",
        )


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


YES_NO_OPTIONS = ["All", "Yes", "No"]


def _yes_no_value(choice: str) -> bool | None:
    return {"Yes": True, "No": False}.get(choice)


def _render_list() -> None:
    flash = st.session_state.pop("po_list_flash", None)
    if flash:
        kind, message = flash
        (st.success if kind == "success" else st.warning if kind == "warning" else st.error)(message)

    col_search, col_hide = st.columns([4, 1.4], vertical_alignment="center")
    with col_search:
        query = st.text_input(
            "Search purchase orders",
            placeholder="Search by PO number or customer name…",
            label_visibility="collapsed",
        )
    with col_hide:
        hide_inactive = st.toggle(
            "Hide archived and voided",
            value=True,
            key="po_hide_inactive",
            help="Hides voided POs and POs for archived customers.",
        )
    try:
        with session_scope() as session:
            order_type_names = list_order_type_names(session)
    except RuntimeError as exc:
        st.error(str(exc))
        return
    col_type, col_invoiced, col_label, col_shipped = st.columns(4)
    with col_type:
        type_choice = st.selectbox("Order type", ["All"] + order_type_names, key="po_filter_type")
    with col_invoiced:
        invoiced_choice = st.selectbox("Invoiced", YES_NO_OPTIONS, key="po_filter_invoiced")
    with col_label:
        label_choice = st.selectbox(
            "Shipping label created", YES_NO_OPTIONS, key="po_filter_label",
            help="Has been sent to ShipStation.",
        )
    with col_shipped:
        shipped_choice = st.selectbox("Shipped", YES_NO_OPTIONS, key="po_filter_shipped")
    invoiced, sent, shipped = (
        _yes_no_value(invoiced_choice),
        _yes_no_value(label_choice),
        _yes_no_value(shipped_choice),
    )

    order_type = None if type_choice == "All" else type_choice
    filters_key = (query, invoiced, sent, shipped, order_type, hide_inactive)
    if st.session_state.get("po_filters_key") != filters_key:
        st.session_state["po_filters_key"] = filters_key
        st.session_state["po_page"] = 1
    page = st.session_state.get("po_page", 1)

    try:
        with session_scope() as session:
            total = count_purchase_orders(
                session,
                query,
                invoiced=invoiced,
                sent_to_shipstation=sent,
                shipped=shipped,
                order_type=order_type,
                hide_inactive=hide_inactive,
            )
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(max(page, 1), total_pages)
            st.session_state["po_page"] = page

            if total:
                purchase_orders = search_purchase_orders(
                    session,
                    query,
                    limit=PAGE_SIZE,
                    offset=(page - 1) * PAGE_SIZE,
                    invoiced=invoiced,
                    sent_to_shipstation=sent,
                    shipped=shipped,
                    order_type=order_type,
                    hide_inactive=hide_inactive,
                )
                po_ids = [po.po_id for po in purchase_orders]
                stats = get_po_line_item_stats(session, po_ids)
                sent_ids = po_ids_sent_to_shipstation(session, po_ids)
            else:
                purchase_orders = []
                stats = {}
                sent_ids = set()
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not purchase_orders:
        st.info("No purchase orders found.")
        return

    # After a bulk send the ticked boxes are cleared - done here, before the
    # checkboxes are created, since a widget's state can't be set after that.
    if st.session_state.pop("po_clear_selection", False):
        for po in purchase_orders:
            st.session_state[f"po_sel_{po.po_id}"] = False

    selected_ids = [po.po_id for po in purchase_orders if st.session_state.get(f"po_sel_{po.po_id}")]
    blocked_selected = {
        po.po_number: shipstation_block_reason(po.order_type)
        for po in purchase_orders
        if po.po_id in selected_ids and shipstation_block_reason(po.order_type)
    }
    if blocked_selected:
        types = sorted({r.split(" orders")[0] for r in blocked_selected.values()})
        st.warning(
            f"{' and '.join(types)} orders aren't sent to ShipStation, so "
            f"{', '.join(blocked_selected)} will be skipped."
        )
    col_label, col_send, col_ship, col_unship, _ = st.columns(
        [1, 1.6, 1.3, 1.4, 1.2], vertical_alignment="center"
    )
    with col_label:
        st.write("Bulk actions:")
    with col_send:
        if st.button(
            "Send to ShipStation",
            type="primary",
            width="stretch",
            disabled=not selected_ids,
            key="po_bulk_send_btn",
        ):
            _start_bulk_send(selected_ids)
    with col_ship:
        if st.button(
            "Mark as shipped", width="stretch", disabled=not selected_ids, key="po_bulk_ship_btn"
        ):
            bulk_ship_confirm_dialog(selected_ids, True)
    with col_unship:
        if st.button(
            "Mark as unshipped", width="stretch", disabled=not selected_ids, key="po_bulk_unship_btn"
        ):
            bulk_ship_confirm_dialog(selected_ids, False)

    render_po_table(purchase_orders, stats, sent_po_ids=sent_ids, selectable=True)

    _render_pagination(page, total_pages, total)


def _run_bulk_ship(po_ids: list[int], shipped: bool) -> None:
    """Marks the POs shipped (or not shipped), skipping the ones it doesn't apply to."""
    done, skipped = [], []
    for po_id in po_ids:
        with session_scope() as session:
            po = get_purchase_order(session, po_id)
            if po is None:
                continue
            number = po.po_number
            if shipped and po.voided:
                skipped.append(f"{number} (voided)")
                continue
            if shipped and po.ship_date is not None:
                skipped.append(f"{number} (already shipped)")
                continue
            if not shipped and po.ship_date is None:
                skipped.append(f"{number} (not shipped)")
                continue
            changed = (
                ship_purchase_order(session, po_id) if shipped else unship_purchase_order(session, po_id)
            )
        if changed is None:
            skipped.append(f"{number} (couldn't be changed)")
            continue
        _sync_po_to_sheet(po_id)
        done.append(number)

    word = "shipped" if shipped else "not shipped"
    parts = []
    if done:
        parts.append(f"Marked {len(done)} order{'' if len(done) == 1 else 's'} as {word}.")
    if skipped:
        parts.append("Skipped: " + "; ".join(skipped) + ".")
    st.session_state["po_list_flash"] = ("warning" if skipped else "success", " ".join(parts) or "Nothing to change.")
    st.session_state["po_clear_selection"] = True
    st.rerun()


@st.dialog("Mark orders", width="small")
def bulk_ship_confirm_dialog(po_ids: list[int], shipped: bool) -> None:
    count = len(po_ids)
    word = "shipped" if shipped else "not shipped"
    st.write(f"Mark {count} selected order{'' if count == 1 else 's'} as {word}?")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Yes", type="primary", width="stretch", key="bulk_ship_yes"):
            _run_bulk_ship(po_ids, shipped)
    with col_no:
        if st.button("Cancel", width="stretch", key="bulk_ship_cancel"):
            st.rerun()


def _start_bulk_send(po_ids: list[int]) -> None:
    """Sorts the ticked POs into ones that can't be sent, ones never sent and ones
    already sent; asks before sending the already-sent ones again."""
    never_sent, already_sent, skipped = [], [], []
    with session_scope() as session:
        sent_before = po_ids_sent_to_shipstation(session, po_ids)
        for po_id in po_ids:
            po = get_purchase_order(session, po_id)
            if po is None:
                continue
            if type_block := shipstation_block_reason(po.order_type):
                skipped.append(f"{po.po_number} ({type_block.split(' orders')[0]} order)")
            elif po.voided or po.ship_date is not None:
                skipped.append(f"{po.po_number} ({'voided' if po.voided else 'already shipped'})")
            elif po.customer is None:
                skipped.append(f"{po.po_number} (no customer)")
            elif po_id in sent_before:
                already_sent.append((po_id, po.po_number))
            else:
                never_sent.append(po_id)
    if already_sent:
        bulk_send_confirm_dialog(already_sent, never_sent, skipped)
    else:
        _run_bulk_send(never_sent, skipped)


def _run_bulk_send(po_ids: list[int], skipped: list[str]) -> None:
    sent, failed, no_weight = [], [], 0
    aborted = None
    with st.spinner("Sending to ShipStation…"):
        for po_id in po_ids:
            try:
                with session_scope() as session:
                    result = send_po(session, po_id)
                    number = get_purchase_order(session, po_id).po_number
            except ShipStationNotConfigured as exc:
                aborted = str(exc)
                break
            except ShipStationError as exc:
                with session_scope() as session:
                    po = get_purchase_order(session, po_id)
                failed.append(f"{po.po_number if po else po_id}: {exc}")
                continue
            sent.append(number)
            if result["weight_lb"] is None:
                no_weight += 1

    parts = []
    if sent:
        parts.append(f"Sent {len(sent)} order{'' if len(sent) == 1 else 's'} to ShipStation.")
    if no_weight:
        parts.append(
            f"{no_weight} had no weight on file - enter it in ShipStation before printing labels."
        )
    if skipped:
        parts.append("Skipped: " + "; ".join(skipped) + ".")
    if failed:
        parts.append("Failed - " + " | ".join(failed))
    if aborted:
        parts.append(aborted)
    if not parts:
        parts.append("Nothing to send.")
    kind = "error" if (failed or aborted) and not sent else "warning" if (failed or aborted or skipped) else "success"
    st.session_state["po_list_flash"] = (kind, " ".join(parts))
    st.session_state["po_clear_selection"] = True
    st.rerun()


@st.dialog("Some orders were already sent", width="small")
def bulk_send_confirm_dialog(
    already_sent: list[tuple[int, str]], never_sent: list[int], skipped: list[str]
) -> None:
    numbers = ", ".join(number for _, number in already_sent)
    st.write(
        f"Some of these orders have already been sent to ShipStation: **{numbers}**. "
        "Sending again creates another order there for each - the earlier ones aren't changed."
    )
    if never_sent:
        st.caption(
            f"{len(never_sent)} other order{' hasn' if len(never_sent) == 1 else 's haven'}'t been sent yet."
        )
    col_again, col_skip, col_cancel = st.columns(3)
    with col_again:
        if st.button("Send again", type="primary", width="stretch", key="bulk_send_again"):
            _run_bulk_send(never_sent + [po_id for po_id, _ in already_sent], skipped)
    with col_skip:
        if st.button("Skip", width="stretch", disabled=not never_sent, key="bulk_send_skip",
                     help="Send only the ones that haven't been sent before."):
            _run_bulk_send(never_sent, skipped + [f"{n} (already sent)" for _, n in already_sent])
    with col_cancel:
        if st.button("Cancel", width="stretch", key="bulk_send_cancel"):
            st.rerun()


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


def render_po_table(
    purchase_orders,
    stats_by_po_id: dict,
    href_base: str = "",
    sent_po_ids: set[int] | None = None,
    selectable: bool = False,
) -> None:
    """Shared PO list markup, used by both the Purchase Orders page and the
    customer detail page's Purchase Orders section, so the two always match.

    href_base is prepended to each row's link - "" for same-page navigation
    (the PO list page itself), "/purchase-orders" for linking in from a
    different page (e.g. the customer detail page).

    sent_po_ids marks POs already sent to ShipStation (a label icon);
    selectable puts a checkbox in front of each row (key po_sel_<po_id>).
    """
    sent_po_ids = sent_po_ids or set()
    header_labels = ["PO Date", "PO Number", "Customer", "Total SKUs", "Total Units", "Order Type", "", ""]
    header = (
        '<div class="po-table-header">'
        + "".join(f"<div>{label}</div>" for label in header_labels)
        + "</div>"
    )

    def row_html(po) -> str:
        return _po_row_html(po, stats_by_po_id.get(po.po_id), href_base, po.po_id in sent_po_ids)

    if not selectable:
        rows_html = "".join(row_html(po) for po in purchase_orders)
        st.markdown(
            f'{PO_CARD_CSS}{header}<div class="po-card-list">{rows_html}</div>',
            unsafe_allow_html=True,
        )
        return

    box_width = [1, 24]
    col_box, col_header = st.columns(box_width)
    with col_header:
        st.markdown(f"{PO_CARD_CSS}{header}", unsafe_allow_html=True)
    for po in purchase_orders:
        with st.container(key=f"porow-{po.po_id}"):
            col_box, col_card = st.columns(box_width, vertical_alignment="center")
            with col_box:
                st.checkbox(
                    f"Select {po.po_number}", key=f"po_sel_{po.po_id}", label_visibility="collapsed"
                )
            with col_card:
                st.markdown(f'<div class="po-card-list" style="padding-top:0">{row_html(po)}</div>', unsafe_allow_html=True)


LABEL_ICON_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" '
    'rx="2"/><path d="M7 9v6M10 9v6M13 9v6M16 9v6M18 9v6"/></svg>'
)


def _po_row_html(po, stats, href_base: str, sent: bool = False) -> str:
    number = html.escape(po.po_number)
    total_skus, total_units = stats if stats else (0, None)
    customer_name = html.escape(po.customer.customer_name) if po.customer else "—"

    card_classes = "po-card"
    if po.voided:
        card_classes += " po-card-voided"
    elif po.ship_date is not None:
        card_classes += " po-card-shipped"

    type_cell = [_order_type_badge_html(po.order_type)]
    if po.voided:
        type_cell.append('<span class="po-badge po-badge-voided">Voided</span>')
    invoice_icon = ""
    if (po.invoice_number or "").strip():
        invoice_title = html.escape(f"Invoice {po.invoice_number.strip()}")
        invoice_icon = f'<span class="po-icon po-icon-invoice" title="{invoice_title}">$</span>'
    label_icon = (
        f'<span class="po-icon po-icon-label" title="Sent to ShipStation">{LABEL_ICON_SVG}</span>'
        if sent
        else ""
    )

    row = (
        '<div class="po-row-grid">'
        f'<div data-label="PO Date">{_format_date(po.order_date)}</div>'
        f'<div class="po-row-number" data-label="PO Number">{number}</div>'
        f'<div data-label="Customer">{customer_name}</div>'
        f'<div data-label="Total SKUs">{total_skus}</div>'
        f'<div data-label="Total Units">{_format_quantity(total_units)}</div>'
        f'<div class="po-row-type-cell" data-label="Order Type">{"".join(type_cell)}</div>'
        f'<div class="po-icon-cell" data-label="Invoiced">{invoice_icon}</div>'
        f'<div class="po-icon-cell" data-label="Sent to ShipStation">{label_icon}</div>'
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
        shipstation_sends = list_sends_for_po(session, po_id) if po else []

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
        st.write(f"**Requested ship date:** {_format_date(po.requested_ship_date)}")

    col_invoice, col_invoice_btn = st.columns([3, 1], vertical_alignment="bottom")
    with col_invoice:
        invoice_text = st.text_input(
            "Invoice number",
            value=po.invoice_number or "",
            max_chars=50,
            key=f"po_invoice_number_{po.po_id}",
        )
    with col_invoice_btn:
        if st.button(
            "Save invoice number",
            width="stretch",
            disabled=invoice_text.strip() == (po.invoice_number or ""),
            key=f"po_invoice_number_save_{po.po_id}",
        ):
            with session_scope() as session:
                set_invoice_number(session, po.po_id, invoice_text)
            st.toast("Invoice number saved.")
            st.rerun()

    col_ship_date, col_ship_btn = st.columns([3, 1])
    with col_ship_date:
        st.write(f"**Ship date:** {_format_datetime(po.ship_date)}")
    with col_ship_btn:
        if po.ship_date is None:
            if st.button("Ship PO", width="stretch", key="ship_po_btn"):
                ship_po_confirm_dialog(po.po_id, po.po_number)
        elif st.button("Mark as unshipped", width="stretch", key="unship_po_btn"):
            unship_po_confirm_dialog(po.po_id, po.po_number)

    if po.note:
        st.write(f"**Note:** {po.note}")

    _render_shipstation_section(po, shipstation_sends)
    _render_quickbooks_section(po.po_id)

    st.subheader("Line items")
    if po.line_items:
        # Prices only show once the PO has any (older POs predate pricing).
        has_prices = any(li.unit_price is not None for li in po.line_items)
        rows = []
        for li in po.line_items:
            row = {
                "SKU": li.sku or (li.item.sku if li.item else ""),
                "Subcategory": (subcategory_name(li.item.category) if li.item else None) or "",
                "Item": li.item.name if li.item else (li.item_description or ""),
                "Current Quantity": li.quantity,
            }
            if has_prices:
                amount = line_amount(li.unit_price, li.quantity)
                row["Price / case"] = f"${li.unit_price:,.2f}" if li.unit_price is not None else "—"
                row["Amount"] = f"${amount:,.2f}" if amount is not None else "—"
            rows.append(row)
        st.dataframe(rows, width="stretch", hide_index=True)
        total, unpriced = order_total(po.line_items)
        if has_prices:
            st.write(f"**Order total:** ${total:,.2f}")
        if unpriced:
            st.caption(
                f"{unpriced} line{'s' if unpriced != 1 else ''} with no price yet - "
                "set it on the customer or customer type Pricing tab, then apply it here. "
                "It isn't in the total, and the order can't go to QuickBooks until every "
                "line is priced."
            )
            if po.customer_id and st.button(
                "Apply current pricing to unpriced lines", key="apply_pricing_btn"
            ):
                with session_scope() as session:
                    filled = price_unpriced_lines(session, po.po_id)
                st.toast(
                    f"Priced {filled} line{'s' if filled != 1 else ''}."
                    if filled
                    else "No pricing is set for those items yet."
                )
                st.rerun()
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


def _render_quickbooks_section(po_id: int) -> None:
    st.subheader("QuickBooks")
    flash = st.session_state.pop("quickbooks_flash", None)
    if flash:
        kind, message = flash
        (st.success if kind == "success" else st.error)(message)

    try:
        with session_scope() as session:
            po = get_purchase_order(session, po_id)
            check = qbo_sync.check_invoice(session, po)
            customer_id = po.customer_id
            attempts = qbo_sync.list_invoice_attempts(session, po_id)
            stale_total = None
            if check.invoice is not None and qbo_sync.invoice_is_stale(po, check.invoice):
                stale_total = qbo_sync.invoice_total(po)
    except (qb.QuickBooksNotConfigured, qb.QuickBooksNotConnected, qb.QuickBooksError) as exc:
        st.caption(f"QuickBooks isn't available: {exc}")
        return

    if check.excluded:
        st.caption(check.excluded)
        return

    if check.invoice is not None:
        invoice = check.invoice
        number = invoice.doc_number or invoice.qbo_invoice_id
        st.write(
            f"**Invoice #{number}** created {_format_datetime(invoice.created_at)} "
            f"· ${invoice.total_amount:,.2f}"
        )
        st.caption("Invoice created in Quickbooks.")
        if stale_total is not None:
            st.warning(
                f"This PO's total is now ${stale_total:,.2f}, but the invoice was created at "
                f"${invoice.total_amount:,.2f}. The invoice in QuickBooks isn't updated "
                "automatically - change it there."
            )
        return

    for reason in check.blockers:
        st.caption(f"• {reason}")
    pending = next((a for a in attempts if a.status == "pending"), None)
    failed = next((a for a in attempts if a.status == "failed"), None)
    if pending:
        st.caption(
            "An earlier attempt didn't finish (QuickBooks couldn't be reached). Trying again "
            "is safe - it won't create a duplicate."
        )
    elif failed and failed.error:
        st.caption(f"Last attempt failed: {failed.error}")
    if st.button(
        "Create invoice in QuickBooks",
        disabled=not check.can_create,
        key="create_qbo_invoice_btn",
    ):
        if check.warnings:
            missing_bill_email_dialog(po_id, customer_id, " ".join(check.warnings))
        else:
            _create_qbo_invoice(po_id)


@st.dialog("No bill-to email")
def missing_bill_email_dialog(po_id: int, customer_id: int, message: str) -> None:
    st.warning(message)
    st.write(
        "QuickBooks will create the invoice with no email on it. You can add one to the "
        "customer first, or create the invoice anyway."
    )
    st.markdown(
        f'<a href="/customers?customer_id={customer_id}" target="_self">'
        "Add an email on the customer →</a>",
        unsafe_allow_html=True,
    )
    col_send, col_cancel = st.columns(2)
    with col_send:
        if st.button("Send anyway", type="primary", width="stretch", key="qbo_send_no_email_btn"):
            _create_qbo_invoice(po_id, send_without_email=True)
    with col_cancel:
        if st.button("Cancel", width="stretch", key="qbo_send_no_email_cancel_btn"):
            st.rerun()


def _create_qbo_invoice(po_id: int, send_without_email: bool = False) -> None:
    try:
        with st.spinner("Creating the invoice in QuickBooks…"):
            with session_scope() as session:
                invoice = qbo_sync.create_invoice(
                    session, po_id, send_without_email=send_without_email
                )
                number = invoice.doc_number or invoice.qbo_invoice_id
                po_filled = getattr(invoice, "po_number_filled", True)
                po_number = get_purchase_order(session, po_id).po_number
        message = f"Created QuickBooks invoice #{number} (unsent)."
        if not po_filled:
            message += (
                f" QuickBooks doesn't let the app fill in PO Reference no. - type "
                f"{po_number} into that box on the invoice."
            )
        st.session_state["quickbooks_flash"] = ("success", message)
    except qbo_sync.InvoiceBlocked as exc:
        st.session_state["quickbooks_flash"] = ("error", " ".join(exc.reasons))
    except (qb.QuickBooksNotConfigured, qb.QuickBooksNotConnected, qb.QuickBooksError) as exc:
        st.session_state["quickbooks_flash"] = ("error", str(exc))
    st.rerun()


def _render_shipstation_section(po, sends) -> None:
    type_block = shipstation_block_reason(po.order_type)
    col_title, col_btn = st.columns([3, 1])
    with col_title:
        st.subheader("ShipStation")
    with col_btn:
        blocked = po.voided or po.ship_date is not None or type_block is not None
        label = "Send again" if sends else "Send to ShipStation"
        if st.button(label, width="stretch", disabled=blocked, key="send_shipstation_btn"):
            if sends:
                resend_shipstation_confirm_dialog(po.po_id, po.po_number, len(sends))
            else:
                _send_po_to_shipstation(po.po_id)

    flash = st.session_state.pop("shipstation_flash", None)
    if flash:
        kind, message = flash
        (st.success if kind == "success" else st.error)(message)

    if type_block:
        st.warning(type_block)
        if not sends:
            return

    if not sends:
        st.write("Not sent to ShipStation yet.")
        return

    latest = sends[0]
    count = len(sends)
    col_sent, col_check = st.columns([3, 1])
    with col_sent:
        st.write(
            f"**Last sent:** {_format_datetime(latest.sent_at)}"
            + (f" ({count} times)" if count > 1 else "")
        )
    with col_check:
        if latest.label_created_at is None and st.button(
            "Check for label", width="stretch", key="check_shipstation_label_btn"
        ):
            _check_shipstation_label(po.po_id, latest.shipstation_order_id)
    if latest.label_created_at:
        tracking = f" · tracking {latest.tracking_number}" if latest.tracking_number else ""
        st.write(f"**Label created:** {_format_datetime(latest.label_created_at)}{tracking}")
        st.caption(
            "A label being created doesn't mean the order has shipped - "
            "use Ship PO once it actually leaves."
        )
    if count > 1 or latest.label_created_at:
        with st.expander("Send history"):
            st.dataframe(
                [
                    {
                        "Sent": _format_datetime(send.sent_at),
                        "ShipStation order ID": send.shipstation_order_id,
                        "Label created": _format_datetime(send.label_created_at),
                        "Tracking": send.tracking_number or "",
                    }
                    for send in sends
                ],
                width="stretch",
                hide_index=True,
            )


def _check_shipstation_label(po_id: int, shipstation_order_id: int) -> None:
    try:
        with st.spinner("Checking ShipStation…"):
            with session_scope() as session:
                sends = [
                    send
                    for send in list_sends_for_po(session, po_id)
                    if send.shipstation_order_id == shipstation_order_id
                    and send.label_created_at is None
                ]
                found = refresh_labels(session, shipstation_order_id, sends)
    except (ShipStationNotConfigured, ShipStationError) as exc:
        st.session_state["shipstation_flash"] = ("error", str(exc))
    else:
        st.session_state["shipstation_flash"] = (
            ("success", "Label found - tracking is below.")
            if found
            else ("error", "No label in ShipStation for this order yet.")
        )
    st.rerun()


def _send_po_to_shipstation(po_id: int) -> None:
    try:
        with st.spinner("Sending to ShipStation…"):
            with session_scope() as session:
                result = send_po(session, po_id)
    except (ShipStationNotConfigured, ShipStationError) as exc:
        st.session_state["shipstation_flash"] = ("error", str(exc))
    else:
        order, shipping = result["order"], result["shipping"]
        weight_lb, missing_weight_skus = result["weight_lb"], result["missing_weight_skus"]
        message = f"Sent to ShipStation (order ID {order['orderId']})."
        if shipping:
            message += f" Shipping method: {shipping['name']}."
        if weight_lb is not None:
            message += f" Weight sent: {weight_lb:.2f} lb."
        else:
            reason = (
                f" - no weight on file for {', '.join(missing_weight_skus)}"
                if missing_weight_skus
                else ""
            )
            message += f" No weight was sent{reason}. Enter it in ShipStation before printing the label."
        st.session_state["shipstation_flash"] = ("success", message)
    st.rerun()


@st.dialog("Send to ShipStation again?", width="small")
def resend_shipstation_confirm_dialog(po_id: int, po_number: str, send_count: int) -> None:
    times = "once" if send_count == 1 else f"{send_count} times"
    st.write(
        f"PO {po_number} has already been sent to ShipStation {times}. Sending again "
        "creates another order there - the earlier one isn't changed, so cancel it in "
        "ShipStation if it's no longer needed."
    )
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Send again", type="primary", width="stretch", key=f"po_resend_{po_id}_yes"):
            _send_po_to_shipstation(po_id)
    with col_no:
        if st.button("Cancel", width="stretch", key=f"po_resend_{po_id}_no"):
            st.rerun()


@st.dialog("Delete purchase order", width="small")
def delete_po_confirm_dialog(po_id: int, po_number: str) -> None:
    st.warning(f"Delete PO {po_number}? This can't be undone.")
    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button("Delete", type="primary", width="stretch", key=f"po_delete_{po_id}_confirm"):
            with session_scope() as session:
                # Grab the line item ids first - they're gone once the PO is.
                doomed = get_purchase_order(session, po_id)
                line_item_ids = [li.line_item_id for li in doomed.line_items] if doomed else []
                deleted = delete_purchase_order(session, po_id)
            if deleted:
                _remove_po_rows_from_sheet(line_item_ids)
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Couldn't delete this PO - make sure it's voided and hasn't shipped.")
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"po_delete_{po_id}_cancel"):
            st.rerun()


@st.dialog("Ship purchase order", width="small")
def ship_po_confirm_dialog(po_id: int, po_number: str) -> None:
    st.write(f"Mark PO {po_number} as shipped?")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Yes", type="primary", width="stretch", key=f"po_ship_{po_id}_yes"):
            with session_scope() as session:
                shipped = ship_purchase_order(session, po_id)
            if shipped is None:
                st.error("Couldn't mark this PO as shipped - it may already have a ship date.")
            else:
                _sync_po_to_sheet(po_id)
                st.rerun()
    with col_no:
        if st.button("No", width="stretch", key=f"po_ship_{po_id}_no"):
            st.rerun()


@st.dialog("Mark PO as not shipped", width="small")
def unship_po_confirm_dialog(po_id: int, po_number: str) -> None:
    st.write(f"Mark PO {po_number} as not shipped? Its ship date will be cleared.")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Yes", type="primary", width="stretch", key=f"po_unship_{po_id}_yes"):
            with session_scope() as session:
                changed = unship_purchase_order(session, po_id)
            if changed is None:
                st.error("Couldn't change this PO - it may not be shipped.")
            else:
                _sync_po_to_sheet(po_id)
                st.rerun()
    with col_no:
        if st.button("No", width="stretch", key=f"po_unship_{po_id}_no"):
            st.rerun()


def _render_new_item_rows(
    key_prefix: str,
    item_choices: list[tuple[int, str, str, str | None]],
    excluded_item_ids: set,
    locked: bool = False,
    default_count: int = 0,
    default_qty: int = 1,
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
        item_choices = list_sellable_item_choices(
            session, exclude_item_ids=existing_item_ids, customer_id=po.customer_id if po else None
        )
        order_type_options = list_order_type_names(session)

    if not po:
        st.error("Purchase order not found.")
        return

    state_prefix = f"po_edit_{po_id}_"

    has_shipped = po.ship_date is not None
    if has_shipped:
        st.warning(
            f"This PO shipped on {_format_datetime(po.ship_date)}. Editing a shipped order "
            "won't change what was actually sent - make sure that's really what you want."
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

    col1, col2, col3, col4 = st.columns(4)
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
        requested_ship_date = st.date_input(
            "Requested ship date",
            value=po.requested_ship_date,
            disabled=locked,
            format=DATE_INPUT_FORMAT,
            key=f"{state_prefix}requested_ship_date",
        )
    with col4:
        # ship_date is a timestamp (set precisely by "Ship PO"), but this
        # widget can only edit the date part - saving combines whatever
        # date is picked here with midnight, since there's no time-of-day
        # control. Manually editing an already-set ship date should be
        # rare; "Ship PO" is the normal path and it does capture the
        # actual time.
        ship_date_only = st.date_input(
            "Ship date",
            value=po.ship_date.date() if po.ship_date else None,
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
                subcategory = (subcategory_name(li.item.category) if li.item else None) or "—"
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
            "border-radius: 0.5rem; padding: 0.25rem 0.5rem; }"
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
            if ship_date_only is None:
                new_ship_date = None
            elif po.ship_date is not None and ship_date_only == po.ship_date.date():
                # Date wasn't actually changed - keep the original time
                # rather than silently collapsing it to midnight just
                # because the form was saved.
                new_ship_date = po.ship_date
            else:
                new_ship_date = datetime.combine(ship_date_only, datetime.min.time())

            with session_scope() as session:
                update_purchase_order(
                    session,
                    po_id,
                    order_type=order_type_choice,
                    order_date=order_date,
                    due_date=due_date,
                    requested_ship_date=requested_ship_date,
                    ship_date=new_ship_date,
                    voided=voided,
                    note=note.strip() or None,
                )
                update_line_item_quantities(session, quantity_updates)
                for item_id, sku, qty in new_rows:
                    add_line_item(session, po_id, item_id, sku, qty)
            _sync_po_to_sheet(po_id)
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
        item_choices = list_sellable_item_choices(session, customer_id=customer_id)
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
        # Ship date itself is deliberately not offered here - it's set via
        # the "Ship PO" action once the order actually ships, not guessed
        # at creation time.
        requested_ship_date = st.date_input(
            "Requested ship date",
            value=None,
            format=DATE_INPUT_FORMAT,
            key=f"{state_prefix}requested_ship_date",
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
                            requested_ship_date=requested_ship_date,
                            note=note.strip() or None,
                            voided=False,
                        )
                        # add_line_item commits, which expires `po`, so grab
                        # the id now - it isn't readable once the session closes.
                        new_po_id = po.po_id
                        for item_id, sku, qty in new_rows:
                            add_line_item(session, new_po_id, item_id, sku, qty)
                except Exception:
                    st.error(
                        f"Couldn't create the PO - a purchase order numbered "
                        f"\"{po_number.strip()}\" may already exist."
                    )
                else:
                    _sync_po_to_sheet(new_po_id)
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
