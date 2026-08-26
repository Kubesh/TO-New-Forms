import html

import streamlit as st

from src.db import session_scope
from src.services.categories import (
    create_category,
    get_category,
    list_items_in_category,
    list_subcategories,
    list_top_level_categories,
    update_category,
)

DEFAULT_COLOR = "#F4591A"

CATEGORY_CARD_CSS = """
<style>
.cat-card-link,
.cat-card-link:visited,
.cat-card-link:hover,
.cat-card-link * {
    color: inherit !important;
    text-decoration: none !important;
}
.cat-card-link {
    display: block;
}
.cat-card-list {
    padding-top: 0.75rem;
}
.cat-card {
    border: 2px solid #1A1712;
    border-left: 6px solid var(--cat-color, #1A1712);
    border-radius: 0.625rem;
    padding: 0.85rem 1rem;
    margin-bottom: 0.75rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.cat-card-name {
    font-size: 1rem;
    font-weight: 700;
}
.cat-card-count {
    font-size: 0.8rem;
    opacity: 0.65;
}
.cat-swatch {
    display: inline-block;
    width: 0.9rem;
    height: 0.9rem;
    border-radius: 999px;
    border: 1px solid rgba(26, 23, 18, 0.3);
    margin-right: 0.5rem;
    vertical-align: middle;
}
</style>
"""


def categories_page() -> None:
    category_id_param = st.query_params.get("category_id")
    if category_id_param:
        try:
            category_id = int(category_id_param)
        except ValueError:
            category_id = None
        if category_id is not None:
            _render_detail(category_id)
            return

    _render_list()


def _render_list() -> None:
    col_title, col_add = st.columns([3, 1])
    with col_title:
        st.title("Categories")
    with col_add:
        st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)
        if st.button("Add Category", width="stretch", key="cat_add_top_level"):
            add_category_dialog()

    try:
        with session_scope() as session:
            top_level = list_top_level_categories(session)
            counts = {
                category.category_id: len(list_subcategories(session, category.category_id))
                for category in top_level
            }
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not top_level:
        st.info("No categories yet - use Add Category to create one.")
        return

    cards_html = "".join(_card_html(category, counts[category.category_id]) for category in top_level)
    st.markdown(
        f'{CATEGORY_CARD_CSS}<div class="cat-card-list">{cards_html}</div>',
        unsafe_allow_html=True,
    )


def _card_html(category, subcategory_count: int) -> str:
    name = html.escape(category.name)
    color = category.color or "#1A1712"
    count_label = f"{subcategory_count} subcategor{'y' if subcategory_count == 1 else 'ies'}"
    return (
        f'<a class="cat-card-link" href="?category_id={category.category_id}" target="_self">'
        f'<div class="cat-card" style="--cat-color: {color};">'
        f'<div class="cat-card-name"><span class="cat-swatch" '
        f'style="background: {color};"></span>{name}</div>'
        f'<div class="cat-card-count">{count_label}</div>'
        "</div></a>"
    )


def _render_detail(category_id: int) -> None:
    try:
        with session_scope() as session:
            category = get_category(session, category_id)
            if category is None:
                st.warning("Category not found.")
                if st.button("← Back to list"):
                    st.query_params.clear()
                    st.rerun()
                return
            subcategories = list_subcategories(session, category_id)
            items = list_items_in_category(session, category.name)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    col_back, col_edit = st.columns([3, 1])
    with col_back:
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
    with col_edit:
        if st.button("Edit category", width="stretch"):
            edit_category_dialog(category_id)

    color = category.color or "#1A1712"
    st.markdown(
        f'<span class="cat-swatch" style="display:inline-block; width:1rem; height:1rem; '
        f'border-radius:999px; border:1px solid rgba(26,23,18,0.3); '
        f'background:{color}; margin-right:0.5rem; vertical-align:middle;"></span>'
        f'<span style="font-size:1.6rem; font-weight:800;">{html.escape(category.name)}</span>',
        unsafe_allow_html=True,
    )

    st.subheader("Subcategories")
    if subcategories:
        for sub in subcategories:
            st.write(f"• {sub.name}")
    else:
        st.caption("No subcategories yet.")
    if st.button("+ Add Subcategory", key="cat_add_sub"):
        add_category_dialog(parent_id=category.category_id, parent_name=category.name)

    st.subheader("Items in this category")
    if not items:
        st.caption("No items in this category yet.")
    else:
        for item in items:
            subcat = f" — {item.subcategory}" if item.subcategory else ""
            st.markdown(
                f'<a href="/items?item_id={item.item_id}" target="_self" '
                f'style="color: inherit; text-decoration: none;">'
                f"<div style='padding: 0.4rem 0; border-bottom: 1px solid rgba(26,23,18,0.12);'>"
                f"<strong>{html.escape(item.name)}</strong>{html.escape(subcat)}"
                f"</div></a>",
                unsafe_allow_html=True,
            )


@st.dialog("Add category")
def add_category_dialog(parent_id: int | None = None, parent_name: str | None = None) -> None:
    if parent_name:
        st.caption(f"Subcategory of {parent_name}")

    name = st.text_input("Name*", key="cat_add_name")

    color = DEFAULT_COLOR
    if parent_id is None:
        color = st.color_picker("Display color", value=DEFAULT_COLOR, key="cat_add_color")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="cat_add_save"):
            if not name.strip():
                st.error("Name is required.")
            else:
                with session_scope() as session:
                    create_category(
                        session,
                        name.strip(),
                        parent_id=parent_id,
                        color=color if parent_id is None else None,
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="cat_add_cancel"):
            st.rerun()


@st.dialog("Edit category")
def edit_category_dialog(category_id: int) -> None:
    with session_scope() as session:
        category = get_category(session, category_id)

    if category is None:
        st.error("Category not found.")
        return

    is_top_level = category.parent_id is None

    name = st.text_input("Name*", value=category.name, key=f"cat_edit_{category_id}_name")
    color = category.color or DEFAULT_COLOR
    if is_top_level:
        color = st.color_picker(
            "Display color", value=color, key=f"cat_edit_{category_id}_color"
        )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key=f"cat_edit_{category_id}_save"):
            if not name.strip():
                st.error("Name is required.")
            else:
                with session_scope() as session:
                    update_category(
                        session,
                        category_id,
                        name=name.strip(),
                        color=color if is_top_level else category.color,
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"cat_edit_{category_id}_cancel"):
            st.rerun()
