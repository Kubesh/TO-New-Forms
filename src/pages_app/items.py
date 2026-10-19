import html

import streamlit as st

from src.db import session_scope
from src.pages_app.category_colors import category_color
from src.services.categories import (
    LEVEL_LABELS,
    MAX_DEPTH,
    SELLABLE_CATEGORY_NAME,
    category_path,
    descendant_ids,
    list_subcategories,
    list_top_level_categories,
)
from src.services.inventory import get_last_count, list_counts_for_item
from src.services.items import count_items, get_item, search_items, update_item
from src.services.purchase_orders import list_line_items_for_item

PAGE_SIZE = 25

ALL_LABELS = {1: "All categories", 2: "All subcategories", 3: "All sub sub categories"}

ITEM_CARD_CSS = """
<style>
.item-card-link,
.item-card-link:visited,
.item-card-link:hover,
.item-card-link * {
    color: inherit !important;
    text-decoration: none !important;
}
.item-card-link {
    display: block;
}
.item-card-list {
    padding-top: 0.75rem;
}
.item-card {
    border: 2px solid #1A1712;
    border-left: 6px solid var(--item-cat-color, #1A1712);
    border-radius: 0.625rem;
    padding: 0.85rem 1rem;
    margin-bottom: 0.75rem;
    box-sizing: border-box;
}
.item-card-sku {
    font-size: 0.75rem;
    font-weight: 600;
    opacity: 0.55;
    letter-spacing: 0.02em;
}
.item-card-name {
    font-size: 1rem;
    font-weight: 700;
    margin-top: 0.15rem;
}
.item-card-sub {
    margin-top: 0.2rem;
    font-size: 0.85rem;
    opacity: 0.75;
}
.item-card-tags {
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
    margin-top: 0.5rem;
}
.item-card-tag {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.1rem 0.5rem;
    border-radius: 999px;
    background: rgba(128, 128, 128, 0.18);
    color: inherit;
}
.item-card-tag-off {
    background: rgba(185, 28, 28, 0.15);
    color: #b91c1c;
}
.item-card-tag-material {
    background: rgba(8, 145, 178, 0.15);
    color: #0891b2;
}
</style>
"""


def _format_date(value) -> str:
    return value.strftime("%m/%d/%y") if value else "—"


def _format_datetime(value) -> str:
    return value.strftime("%m/%d/%y %-I:%M %p") if value else "—"


def _format_counted(counted) -> str:
    """Displayed rounded to 1 decimal place (68.00000000 -> 68,
    695.7194207 -> 695.7) - the column itself keeps full precision, this
    is display-only."""
    if counted is None:
        return "—"
    text = f"{counted:.1f}".rstrip("0").rstrip(".")
    return text or "0"


def category_subcategory_picker(session, current_category, key_prefix: str) -> int | None:
    """Renders a selectbox per category level (category, subcategory, form
    factor), each scoped to whatever is chosen above it, and returns the
    category_id that should end up on the item - the deepest level picked,
    or None if no category is."""
    path = category_path(current_category)
    parent_id = None
    chosen_id = None
    root_name = None
    columns = st.columns(MAX_DEPTH)
    for level in range(1, MAX_DEPTH + 1):
        if level == MAX_DEPTH and root_name != SELLABLE_CATEGORY_NAME:
            break  # sub sub categories only exist under Sellable Product
        label = LEVEL_LABELS[level]
        none_label = "No category" if level == 1 else f"No {label.lower()}"
        if level == 1:
            options = list_top_level_categories(session)
        elif chosen_id is not None:
            options = list_subcategories(session, chosen_id)
        else:
            options = []
        names = [none_label] + [c.name for c in options]
        by_name = {c.name: c for c in options}

        # The item's current value is only the default while the levels above
        # still match its path; keying on the parent means switching a higher
        # level always resets this one instead of carrying over a value that
        # may not exist in the new parent's list.
        on_path = len(path) >= level and (level == 1 or path[level - 2].category_id == chosen_id)
        index = names.index(path[level - 1].name) if on_path and path[level - 1].name in names else 0
        with columns[level - 1]:
            choice = st.selectbox(
                label,
                names,
                index=index,
                disabled=chosen_id is None and level > 1,
                key=f"{key_prefix}level{level}_{chosen_id}",
            )
        if choice == none_label:
            # Nothing picked at this level: the deeper ones stay empty.
            chosen_here = None
        else:
            chosen_here = by_name[choice].category_id
        if chosen_here is None:
            for deeper in range(level + 1, MAX_DEPTH + 1):
                if deeper == MAX_DEPTH and root_name != SELLABLE_CATEGORY_NAME:
                    break
                with columns[deeper - 1]:
                    st.selectbox(
                        LEVEL_LABELS[deeper],
                        [f"No {LEVEL_LABELS[deeper].lower()}"],
                        disabled=True,
                        key=f"{key_prefix}level{deeper}_none",
                    )
            break
        chosen_id = chosen_here
        if level == 1:
            root_name = choice
    return chosen_id


def items_page() -> None:
    item_id_param = st.query_params.get("item_id")
    if item_id_param:
        try:
            item_id = int(item_id_param)
        except ValueError:
            item_id = None
        if item_id is not None:
            _render_detail(item_id)
            return

    _render_list()


def _render_list() -> None:
    st.title("Items")

    col_search, col_sellable = st.columns([3, 1])
    with col_search:
        query = st.text_input(
            "Search items",
            placeholder="Search by name or SKU…",
            label_visibility="collapsed",
        )
    with col_sellable:
        st.markdown("<div style='height: 0.4rem'></div>", unsafe_allow_html=True)
        sellable_only = st.checkbox("Sellable only")
    sellable = True if sellable_only else None

    # One filter per category level, each only offered once the level above
    # is picked - without that, names from unrelated categories would be mixed.
    # Keying each on its parent means picking a new parent starts the next
    # level fresh at "All" instead of carrying over a value that may not exist
    # in the new parent's list (which would crash - Streamlit rejects a
    # selectbox whose session-state value isn't in its current options).
    chosen_id = None
    try:
        with session_scope() as session:
            columns = st.columns(MAX_DEPTH)
            root_name = None
            for level in range(1, MAX_DEPTH + 1):
                if level == MAX_DEPTH and root_name != SELLABLE_CATEGORY_NAME:
                    break  # sub sub categories only exist under Sellable Product
                if level == 1:
                    options = list_top_level_categories(session)
                elif chosen_id is not None:
                    options = list_subcategories(session, chosen_id)
                else:
                    break
                if not options and level > 1:
                    break
                all_label = ALL_LABELS[level]
                with columns[level - 1]:
                    choice = st.selectbox(
                        LEVEL_LABELS[level],
                        [all_label] + [c.name for c in options],
                        key=f"items_filter_level{level}_{chosen_id}",
                    )
                picked = next((c for c in options if c.name == choice), None)
                if picked is None:
                    break
                chosen_id = picked.category_id
                if level == 1:
                    root_name = picked.name
            category_ids = descendant_ids(session, chosen_id) if chosen_id is not None else None
    except RuntimeError as exc:
        st.error(str(exc))
        return

    filters_key = (query, tuple(category_ids) if category_ids else None, sellable)
    if st.session_state.get("item_filters_key") != filters_key:
        st.session_state["item_filters_key"] = filters_key
        st.session_state["item_page"] = 1
    page = st.session_state.get("item_page", 1)

    try:
        with session_scope() as session:
            total = count_items(session, query, category_ids, sellable)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(max(page, 1), total_pages)
            st.session_state["item_page"] = page

            if total:
                items = search_items(
                    session,
                    query,
                    category_ids,
                    sellable,
                    limit=PAGE_SIZE,
                    offset=(page - 1) * PAGE_SIZE,
                )
            else:
                items = []
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not items:
        st.info("No items found.")
        return

    cards_html = "".join(_card_html(item) for item in items)
    st.markdown(
        f'{ITEM_CARD_CSS}<div class="item-card-list">{cards_html}</div>',
        unsafe_allow_html=True,
    )

    _render_pagination(page, total_pages, total)


def _render_pagination(page: int, total_pages: int, total: int) -> None:
    start = (page - 1) * PAGE_SIZE + 1
    end = min(page * PAGE_SIZE, total)
    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("← Previous", disabled=page <= 1, width="stretch", key="item_prev"):
            st.session_state["item_page"] = page - 1
            st.rerun()
    with col_info:
        st.markdown(
            f'<div style="text-align:center; padding-top: 0.4rem;">'
            f"Showing {start}–{end} of {total} · Page {page} of {total_pages}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button("Next →", disabled=page >= total_pages, width="stretch", key="item_next"):
            st.session_state["item_page"] = page + 1
            st.rerun()


def _card_html(item) -> str:
    color = category_color(item.category)
    name = html.escape(item.name)
    sku = html.escape(item.sku)
    subcategory_line = html.escape(" / ".join(c.name for c in category_path(item.category)))

    tags = []
    if not item.sellable:
        tags.append('<span class="item-card-tag item-card-tag-off">Not sellable</span>')
    if item.shipping_material:
        tags.append('<span class="item-card-tag item-card-tag-material">Shipping material</span>')

    parts = [
        f'<a class="item-card-link" href="?item_id={item.item_id}" target="_self">',
        f'<div class="item-card" style="--item-cat-color: {color};">',
        f'<div class="item-card-sku">{sku}</div>',
        f'<div class="item-card-name">{name}</div>',
    ]
    if subcategory_line:
        parts.append(f'<div class="item-card-sub">{subcategory_line}</div>')
    if tags:
        parts.append(f'<div class="item-card-tags">{"".join(tags)}</div>')
    parts.append("</div></a>")
    return "".join(parts)


def _render_detail(item_id: int) -> None:
    with session_scope() as session:
        item = get_item(session, item_id)

    if not item:
        st.warning("Item not found.")
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
        if st.button("Edit item", width="stretch"):
            edit_item_dialog(item.item_id)

    st.caption(item.sku)
    st.header(item.name)

    path_names = [c.name for c in category_path(item.category)]
    st.write(" / ".join(path_names) if path_names else "No category")

    if not item.sellable:
        st.badge("Not sellable", color="red")
    if item.shipping_material:
        st.badge("Shipping material", color="blue")

    try:
        with session_scope() as session:
            last_count = get_last_count(session, item.item_id)
            counts = list_counts_for_item(session, item.item_id)
            order_line_items = (
                list_line_items_for_item(session, item.item_id) if item.sellable else []
            )
    except RuntimeError as exc:
        st.error(str(exc))
        return

    tab_names = ["Overview", "Counts", "Details"]
    if item.sellable:
        tab_names.append("Orders")
    tabs = st.tabs(tab_names)
    tab_overview, tab_counts, tab_details = tabs[0], tabs[1], tabs[2]
    tab_orders = tabs[3] if item.sellable else None

    with tab_overview:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Current on hand", _format_counted(last_count.counted) if last_count else "—")
        with col2:
            st.metric("Last count", _format_date(last_count.created_at) if last_count else "—")
        with col3:
            # Would need sales/shipment consumption tracked against
            # inventory to compute this - not wired up yet, so this is a
            # placeholder rather than a real (or worse, wrong) number.
            st.metric("Used since last count", "—")
            st.caption("Not tracked yet")

    with tab_counts:
        if not counts:
            st.caption("No counts recorded yet.")
        else:
            for count in counts:
                col_date, col_count, col_note = st.columns([1.5, 1, 3])
                with col_date:
                    st.write(_format_datetime(count.created_at))
                with col_count:
                    st.write(_format_counted(count.counted))
                with col_note:
                    st.write(count.notes or "—")

    with tab_details:
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Measured in:** {item.measured_in or '—'}")
            st.write(
                f"**Unit weight (lb):** "
                f"{item.unit_weight_lb if item.unit_weight_lb is not None else '—'}"
            )
            st.write(
                f"**Sellable content weight (lb):** "
                f"{item.sellable_content_weight_lb if item.sellable_content_weight_lb is not None else '—'}"
            )
        with col2:
            st.write(f"**Shopify item #:** {item.shopify_item_number or '—'}")
            st.write(f"**Shopify variant #:** {item.shopify_variant_number or '—'}")
        if item.search_terms:
            st.write(f"**Search terms:** {item.search_terms}")

    if tab_orders is not None:
        with tab_orders:
            if not order_line_items:
                st.caption("No orders for this item yet.")
            else:
                header_cols = st.columns([1.5, 3, 1.5, 1])
                for col, label in zip(header_cols, ["Date", "Customer", "PO Number", "Qty"]):
                    with col:
                        st.caption(label)
                for line_item in order_line_items:
                    po = line_item.purchase_order
                    customer_name = po.customer.customer_name if po.customer else "—"
                    row_cols = st.columns([1.5, 3, 1.5, 1])
                    with row_cols[0]:
                        st.write(_format_date(po.order_date))
                    with row_cols[1]:
                        st.markdown(
                            f'<a href="/purchase-orders?po_id={po.po_id}" target="_self" '
                            f'style="color: inherit; text-decoration: none;">'
                            f"{html.escape(customer_name)}</a>",
                            unsafe_allow_html=True,
                        )
                    with row_cols[2]:
                        st.write(po.po_number)
                    with row_cols[3]:
                        st.write(str(line_item.quantity))


@st.dialog("Edit item", width="large")
def edit_item_dialog(item_id: int) -> None:
    with session_scope() as session:
        item = get_item(session, item_id)

    if not item:
        st.error("Item not found.")
        return

    state_prefix = f"item_edit_{item_id}_"

    st.caption(item.sku)
    name = st.text_input("Name*", value=item.name, key=f"{state_prefix}name")

    with session_scope() as session:
        category_id = category_subcategory_picker(session, item.category, state_prefix)

    col3, col4 = st.columns(2)
    with col3:
        unit_weight_lb = st.number_input(
            "Unit weight (lb)",
            value=float(item.unit_weight_lb) if item.unit_weight_lb is not None else 0.0,
            min_value=0.0,
            step=0.01,
            format="%.4f",
            key=f"{state_prefix}unit_weight",
        )
    with col4:
        sellable_content_weight_lb = st.number_input(
            "Sellable content weight (lb)",
            value=(
                float(item.sellable_content_weight_lb)
                if item.sellable_content_weight_lb is not None
                else 0.0
            ),
            min_value=0.0,
            step=0.01,
            format="%.4f",
            key=f"{state_prefix}sellable_weight",
        )

    measured_in_options = ["Eaches", "Pounds"]
    current_measured_in = item.measured_in if item.measured_in in measured_in_options else "Eaches"
    measured_in = st.selectbox(
        "Measured in",
        measured_in_options,
        index=measured_in_options.index(current_measured_in),
        key=f"{state_prefix}measured_in",
    )

    col5, col6 = st.columns(2)
    with col5:
        shopify_item_number = st.text_input(
            "Shopify item #",
            value=item.shopify_item_number or "",
            key=f"{state_prefix}shopify_item",
        )
    with col6:
        shopify_variant_number = st.text_input(
            "Shopify variant #",
            value=item.shopify_variant_number or "",
            key=f"{state_prefix}shopify_variant",
        )

    search_terms = st.text_area(
        "Search terms", value=item.search_terms or "", key=f"{state_prefix}search_terms"
    )

    col7, col8 = st.columns(2)
    with col7:
        sellable = st.checkbox("Sellable", value=item.sellable, key=f"{state_prefix}sellable")
    with col8:
        shipping_material = st.checkbox(
            "Shipping material", value=item.shipping_material, key=f"{state_prefix}shipping"
        )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key=f"{state_prefix}save"):
            if not name.strip():
                st.error("Name is required.")
            else:
                with session_scope() as session:
                    update_item(
                        session,
                        item_id,
                        name=name.strip(),
                        category_id=category_id,
                        measured_in=measured_in.strip() or None,
                        unit_weight_lb=unit_weight_lb or None,
                        sellable_content_weight_lb=sellable_content_weight_lb or None,
                        shopify_item_number=shopify_item_number.strip() or None,
                        shopify_variant_number=shopify_variant_number.strip() or None,
                        search_terms=search_terms.strip() or None,
                        sellable=sellable,
                        shipping_material=shipping_material,
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"{state_prefix}cancel"):
            st.rerun()
