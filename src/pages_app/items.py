import html

import streamlit as st

from src.db import session_scope
from src.pages_app.category_colors import category_color
from src.services.categories import get_category_color_map
from src.services.items import (
    count_items,
    get_item,
    list_distinct_categories,
    list_distinct_subcategories,
    search_items,
    update_item,
)

PAGE_SIZE = 25

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

    try:
        with session_scope() as session:
            categories = list_distinct_categories(session)
            color_map = get_category_color_map(session)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    col_search, col_category, col_sellable = st.columns([2, 1, 1])
    with col_search:
        query = st.text_input(
            "Search items",
            placeholder="Search by name or SKU…",
            label_visibility="collapsed",
        )
    with col_category:
        category_choice = st.selectbox("Category", ["All categories"] + categories)
    with col_sellable:
        st.markdown("<div style='height: 1.85rem'></div>", unsafe_allow_html=True)
        sellable_only = st.checkbox("Sellable only")

    category = None if category_choice == "All categories" else category_choice
    sellable = True if sellable_only else None

    # Subcategory only makes sense once a category is picked - without one,
    # subcategory names from unrelated categories would be mixed together.
    subcategory = None
    if category:
        try:
            with session_scope() as session:
                subcategories = list_distinct_subcategories(session, category=category)
        except RuntimeError as exc:
            st.error(str(exc))
            return

        # Keying the subcategory picker on the current category means picking
        # a new category always starts it fresh at "All subcategories" instead
        # of carrying over a value that may not exist in the new category's
        # list (which would otherwise crash - Streamlit rejects a selectbox
        # whose session-state value isn't in its current options).
        subcategory_choice = st.selectbox(
            "Subcategory",
            ["All subcategories"] + subcategories,
            key=f"items_subcategory_{category_choice}",
        )
        subcategory = None if subcategory_choice == "All subcategories" else subcategory_choice

    filters_key = (query, category, subcategory, sellable)
    if st.session_state.get("item_filters_key") != filters_key:
        st.session_state["item_filters_key"] = filters_key
        st.session_state["item_page"] = 1
    page = st.session_state.get("item_page", 1)

    try:
        with session_scope() as session:
            total = count_items(session, query, category, subcategory, sellable)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(max(page, 1), total_pages)
            st.session_state["item_page"] = page

            if total:
                items = search_items(
                    session,
                    query,
                    category,
                    subcategory,
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

    cards_html = "".join(_card_html(item, color_map) for item in items)
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


def _card_html(item, color_map: dict[str, str]) -> str:
    color = category_color(item.category, color_map)
    name = html.escape(item.name)
    sku = html.escape(item.sku)
    subcategory_bits = [b for b in [item.category, item.subcategory] if b]
    subcategory_line = html.escape(" / ".join(subcategory_bits)) if subcategory_bits else ""

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

    subcategory_bits = [b for b in [item.category, item.subcategory] if b]
    st.write(" / ".join(subcategory_bits) if subcategory_bits else "No category")

    if not item.sellable:
        st.badge("Not sellable", color="red")
    if item.shipping_material:
        st.badge("Shipping material", color="blue")

    st.subheader("Details")
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

    col1, col2 = st.columns(2)
    with col1:
        category = st.text_input(
            "Category", value=item.category or "", key=f"{state_prefix}category"
        )
    with col2:
        subcategory = st.text_input(
            "Subcategory", value=item.subcategory or "", key=f"{state_prefix}subcategory"
        )

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

    measured_in = st.text_input(
        "Measured in", value=item.measured_in or "", key=f"{state_prefix}measured_in"
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
                        category=category.strip() or None,
                        subcategory=subcategory.strip() or None,
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
