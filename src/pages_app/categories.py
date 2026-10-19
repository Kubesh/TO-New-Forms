import html

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

from src.db import session_scope
from src.services.categories import (
    LEVEL_LABELS,
    MAX_DEPTH,
    category_depth,
    category_path,
    create_category,
    get_category,
    list_items_in_category,
    list_subcategories,
    list_top_level_categories,
    move_items_to_categories,
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

    # Clicking "Categories" in the sidebar re-runs this page but leaves the
    # browser URL as it was, so clear a stale category_id (as the Customers
    # page does).
    st.query_params.clear()
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


def _child_count_label(depth: int, count: int) -> str:
    """How a category at this depth counts its children."""
    if depth == 1:
        return f"{count} subcategor{'y' if count == 1 else 'ies'}"
    return f"{count} form factor{'' if count == 1 else 's'}"


def _card_html(category, subcategory_count: int, depth: int = 1, color: str | None = None) -> str:
    name = html.escape(category.name)
    color = color or category.color or "#1A1712"
    count_label = _child_count_label(depth, subcategory_count) if depth < MAX_DEPTH else ""
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
            path = category_path(category)
            depth = len(path)
            children = list_subcategories(session, category_id)
            child_counts = {
                child.category_id: len(list_subcategories(session, child.category_id))
                for child in children
            }
            items = list_items_in_category(session, category_id)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    parent = path[-2] if depth > 1 else None
    col_back, col_edit = st.columns([3, 1])
    with col_back:
        if st.button(f"← Back to {parent.name}" if parent else "← Back to list"):
            if parent:
                st.query_params["category_id"] = str(parent.category_id)
            else:
                st.query_params.clear()
            st.rerun()
    with col_edit:
        if st.button(f"Edit {LEVEL_LABELS[depth].lower()}", width="stretch"):
            edit_category_dialog(category_id)

    color = path[0].color or "#1A1712"
    st.markdown(
        f'<span class="cat-swatch" style="display:inline-block; width:1rem; height:1rem; '
        f'border-radius:999px; border:1px solid rgba(26,23,18,0.3); '
        f'background:{color}; margin-right:0.5rem; vertical-align:middle;"></span>'
        f'<span style="font-size:1.6rem; font-weight:800;">{html.escape(category.name)}</span>',
        unsafe_allow_html=True,
    )
    st.caption(" › ".join(c.name for c in path) + f"  ·  {LEVEL_LABELS[depth]}")

    if depth < MAX_DEPTH:
        child_label = LEVEL_LABELS[depth + 1]
        if st.button(f"+ Add {child_label.lower()}", key="cat_add_child"):
            add_category_dialog(
                parent_id=category.category_id,
                parent_name=category.name,
                child_label=child_label,
            )
        if children:
            cards = "".join(
                _card_html(child, child_counts[child.category_id], depth + 1, color)
                for child in children
            )
            st.markdown(
                f'{CATEGORY_CARD_CSS}<div class="cat-card-list">{cards}</div>',
                unsafe_allow_html=True,
            )

    if depth == 2 and children:
        with st.expander("Assign items to form factors"):
            _render_form_factor_assignment(category, children, items)

    st.subheader(f"Items ({len(items)})")
    _render_item_list(items, show_subcategory=depth < MAX_DEPTH)


def _render_form_factor_assignment(line, form_factors, items) -> None:
    """Bulk-moves this line's items between its form factors (and back onto
    the line itself)."""
    if not items:
        st.caption("No items in this line yet.")
        return
    none_label = "(none - directly on the line)"
    by_name = {ff.name: ff.category_id for ff in form_factors}
    current = {
        item.item_id: next(
            (ff.name for ff in form_factors if ff.category_id == item.category_id), none_label
        )
        for item in items
    }
    frame = pd.DataFrame(
        [{"SKU": i.sku, "Item": i.name, "Form factor": current[i.item_id]} for i in items]
    )
    version_key = f"ff_assign_version_{line.category_id}"
    version = st.session_state.get(version_key, 0)
    edited = st.data_editor(
        frame,
        hide_index=True,
        width="stretch",
        disabled=["SKU", "Item"],
        column_config={
            "Form factor": st.column_config.SelectboxColumn(
                "Form factor", options=[none_label] + list(by_name), required=True
            )
        },
        key=f"ff_assign_{line.category_id}_{version}",
    )
    moves = {
        item.item_id: line.category_id if choice == none_label else by_name[choice]
        for item, choice in zip(items, edited["Form factor"])
        if choice != current[item.item_id]
    }
    if st.button(
        "Save assignments",
        type="primary",
        disabled=not moves,
        key=f"ff_assign_save_{line.category_id}",
    ):
        with session_scope() as session:
            move_items_to_categories(session, moves)
        st.session_state[version_key] = version + 1
        st.toast(f"Moved {len(moves)} item{'' if len(moves) == 1 else 's'}.")
        st.rerun()


def _render_item_list(items, show_subcategory: bool) -> None:
    if not items:
        st.caption("No items here yet.")
        return
    for item in items:
        below_top = [c.name for c in category_path(item.category)[1:]]
        subcat = f" — {' › '.join(below_top)}" if show_subcategory and below_top else ""
        st.markdown(
            f'<a href="/items?item_id={item.item_id}" target="_self" '
            f'style="color: inherit; text-decoration: none;">'
            f"<div style='padding: 0.4rem 0; border-bottom: 1px solid rgba(26,23,18,0.12);'>"
            f"<strong>{html.escape(item.name)}</strong>{html.escape(subcat)}"
            f"</div></a>",
            unsafe_allow_html=True,
        )


@st.dialog("Add category")
def add_category_dialog(
    parent_id: int | None = None, parent_name: str | None = None, child_label: str = "Subcategory"
) -> None:
    if parent_name:
        st.caption(f"{child_label} of {parent_name}")

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
                try:
                    with session_scope() as session:
                        create_category(
                            session,
                            name.strip(),
                            parent_id=parent_id,
                            color=color if parent_id is None else None,
                        )
                except (ValueError, IntegrityError) as exc:
                    st.error(
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "A category with that name already exists here."
                    )
                else:
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
                try:
                    with session_scope() as session:
                        update_category(
                            session,
                            category_id,
                            name=name.strip(),
                            color=color if is_top_level else category.color,
                        )
                except IntegrityError:
                    st.error("A category with that name already exists here.")
                else:
                    st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"cat_edit_{category_id}_cancel"):
            st.rerun()
