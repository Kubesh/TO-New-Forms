import html

import streamlit as st

from src.db import session_scope
from src.services.items import (
    count_items,
    list_distinct_categories,
    list_distinct_subcategories,
    search_items,
)

PAGE_SIZE = 25

CATEGORY_PALETTE = [
    "#F4591A",  # orange
    "#1D4ED8",  # blue
    "#059669",  # green
    "#7C3AED",  # violet
    "#B45309",  # amber
    "#DB2777",  # pink
    "#0891B2",  # cyan
    "#65A30D",  # lime
    "#DC2626",  # red
    "#4338CA",  # indigo
]

ITEM_CARD_CSS = """
<style>
.item-card-list {
    padding-top: 0.75rem;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 0.75rem;
}
.item-card {
    border: 2px solid #1A1712;
    border-left: 6px solid var(--item-cat-color, #1A1712);
    border-radius: 0.625rem;
    padding: 0.85rem 1rem;
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


def _category_color(category: str | None, sorted_categories: list[str]) -> str:
    if not category or category not in sorted_categories:
        return "rgba(128, 128, 128, 0.35)"
    return CATEGORY_PALETTE[sorted_categories.index(category) % len(CATEGORY_PALETTE)]


def items_page() -> None:
    st.title("Items")

    try:
        with session_scope() as session:
            categories = list_distinct_categories(session)
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
        sellable_choice = st.selectbox("Sellable", ["All items", "Sellable only", "Not sellable"])

    category = None if category_choice == "All categories" else category_choice

    try:
        with session_scope() as session:
            subcategories = list_distinct_subcategories(session, category=category)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    # Keying the subcategory picker on the current category means changing
    # category always starts it fresh at "All subcategories" instead of
    # carrying over a value that may not exist in the new category's list
    # (which would otherwise crash - Streamlit rejects a selectbox whose
    # session-state value isn't in its current options).
    subcategory_choice = st.selectbox(
        "Subcategory", ["All subcategories"] + subcategories, key=f"items_subcategory_{category_choice}"
    )
    subcategory = None if subcategory_choice == "All subcategories" else subcategory_choice

    sellable = {"Sellable only": True, "Not sellable": False}.get(sellable_choice)

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

    sorted_categories = sorted(categories)
    cards_html = "".join(_card_html(item, sorted_categories) for item in items)
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


def _card_html(item, sorted_categories: list[str]) -> str:
    color = _category_color(item.category, sorted_categories)
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
        f'<div class="item-card" style="--item-cat-color: {color};">',
        f'<div class="item-card-sku">{sku}</div>',
        f'<div class="item-card-name">{name}</div>',
    ]
    if subcategory_line:
        parts.append(f'<div class="item-card-sub">{subcategory_line}</div>')
    if tags:
        parts.append(f'<div class="item-card-tags">{"".join(tags)}</div>')
    parts.append("</div>")
    return "".join(parts)
