import html
from datetime import date

import streamlit as st

from src.db import session_scope
from src.services.assemblies import list_assemblies
from src.services.batches import (
    add_batch_item,
    create_batch,
    delete_batch_item,
    get_batch,
    get_batch_item,
    list_batch_choices,
    list_current_batches,
    release_batch,
    update_batch,
    update_batch_item,
)
from src.services.items import list_all_item_choices

DATE_INPUT_FORMAT = "MM/DD/YYYY"  # Streamlit's date_input only supports 4-digit years

BATCH_CARD_CSS = """
<style>
.batch-card-link,
.batch-card-link:visited,
.batch-card-link:hover,
.batch-card-link * {
    color: inherit !important;
    text-decoration: none !important;
}
.batch-card-link {
    display: block;
}
.batch-card-list {
    padding-top: 0.75rem;
}
.batch-card {
    border: 2px solid #1A1712;
    border-radius: 0.625rem;
    padding: 0.85rem 1rem;
    margin-bottom: 0.75rem;
}
.batch-card-code {
    font-size: 1rem;
    font-weight: 700;
}
.batch-card-recipe {
    font-size: 0.85rem;
    opacity: 0.75;
    margin-top: 0.1rem;
}
.batch-card-meta {
    font-size: 0.8rem;
    opacity: 0.65;
    margin-top: 0.3rem;
}
</style>
"""


def _format_date(value) -> str:
    return value.strftime("%m/%d/%y") if value else "—"


def _format_datetime(value) -> str:
    return value.strftime("%m/%d/%y %-I:%M %p") if value else "—"


def batches_page() -> None:
    batch_id_param = st.query_params.get("batch_id")
    if batch_id_param:
        try:
            batch_id = int(batch_id_param)
        except ValueError:
            batch_id = None
        if batch_id is not None:
            _render_detail(batch_id)
            return

    _render_list()


def _render_list() -> None:
    col_title, col_add = st.columns([3, 1])
    with col_title:
        st.title("Batches")
    with col_add:
        st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)
        if st.button("Add Batch", width="stretch", key="batch_add"):
            add_batch_dialog()

    st.caption("Batches currently being worked on - released batches aren't shown here.")

    try:
        with session_scope() as session:
            batches = list_current_batches(session)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not batches:
        st.info("No batches in progress - use Add Batch to start one.")
        return

    cards_html = "".join(_card_html(batch) for batch in batches)
    st.markdown(
        f'{BATCH_CARD_CSS}<div class="batch-card-list">{cards_html}</div>',
        unsafe_allow_html=True,
    )


def _card_html(batch) -> str:
    code = html.escape(batch.batch_code)
    recipe = html.escape(f"{batch.version.assembly.assembly_name} — {batch.version.version_name}")
    item_count = len(batch.items)
    count_label = f"{item_count} item{'s' if item_count != 1 else ''}"
    created = _format_date(batch.created_at)
    return (
        f'<a class="batch-card-link" href="?batch_id={batch.batch_id}" target="_self">'
        f'<div class="batch-card">'
        f'<div class="batch-card-code">{code}</div>'
        f'<div class="batch-card-recipe">{recipe}</div>'
        f'<div class="batch-card-meta">Started {created} · {count_label}</div>'
        "</div></a>"
    )


def _render_detail(batch_id: int) -> None:
    try:
        with session_scope() as session:
            batch = get_batch(session, batch_id)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if batch is None:
        st.warning("Batch not found.")
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
        return

    col_back, col_release, col_edit = st.columns([3, 1, 1])
    with col_back:
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
    with col_release:
        if batch.released_at is None:
            if st.button("Release batch", width="stretch"):
                with session_scope() as session:
                    release_batch(session, batch.batch_id)
                st.rerun()
    with col_edit:
        if st.button("Edit batch", width="stretch"):
            edit_batch_dialog(batch.batch_id)

    st.header(batch.batch_code)
    st.caption(f"{batch.version.assembly.assembly_name} — {batch.version.version_name}")

    if batch.parent is not None:
        st.markdown(
            f'<a href="?batch_id={batch.parent.batch_id}" target="_self" '
            f'style="color: inherit;">Parent batch: {html.escape(batch.parent.batch_code)}</a>',
            unsafe_allow_html=True,
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Started", _format_date(batch.created_at))
    with col2:
        st.metric("Expires", _format_date(batch.expire_date))
    with col3:
        st.metric("Released", _format_datetime(batch.released_at) if batch.released_at else "Not yet")

    if batch.notes:
        st.write(batch.notes)

    st.subheader("Items")
    if st.button("+ Add Item", key="batch_add_item"):
        add_batch_item_dialog(batch.batch_id)

    if not batch.items:
        st.caption("No items in this batch yet.")
        return

    header_cols = st.columns([2.5, 1.3, 1, 1.5, 1])
    for col, label in zip(header_cols, ["Product", "Role", "Units", "Lot #", ""]):
        with col:
            st.caption(label)

    for batch_item in batch.items:
        row_cols = st.columns([2.5, 1.3, 1, 1.5, 1])
        with row_cols[0]:
            st.markdown(
                f'<a href="/items?item_id={batch_item.product.item_id}" target="_self" '
                f'style="color: inherit; text-decoration: none;">'
                f"<strong>{html.escape(batch_item.product.name)}</strong> "
                f"<span style='opacity:0.6;'>({html.escape(batch_item.product.sku)})</span>"
                f"</a>",
                unsafe_allow_html=True,
            )
        with row_cols[1]:
            if batch_item.units < 0:
                st.markdown("<span style='color:#b91c1c;'>Consumed</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#059669;'>Produced</span>", unsafe_allow_html=True)
        with row_cols[2]:
            st.write(_format_units(batch_item.units))
        with row_cols[3]:
            st.write(batch_item.lot_number or "—")
        with row_cols[4]:
            action_cols = st.columns(2)
            with action_cols[0]:
                if st.button("✎", key=f"batch_item_edit_{batch_item.batch_item_id}", help="Edit"):
                    edit_batch_item_dialog(batch_item.batch_item_id)
            with action_cols[1]:
                if st.button("✕", key=f"batch_item_del_{batch_item.batch_item_id}", help="Remove"):
                    with session_scope() as session:
                        delete_batch_item(session, batch_item.batch_item_id)
                    st.rerun()


def _format_units(units: float) -> str:
    text = f"{units:.4f}".rstrip("0").rstrip(".") or "0"
    return text if text.startswith("-") else f"+{text}"


def _version_picker(session, key_prefix: str) -> int | None:
    """Assembly then version selectboxes, scoped like the category picker -
    returns the chosen assembly_version_id, or None if there's nothing to
    pick from."""
    assemblies = list_assemblies(session)
    assemblies = [a for a in assemblies if a.versions]
    if not assemblies:
        st.warning("No assemblies with versions exist yet - create one on the Assemblies page.")
        return None

    assembly_labels = [a.assembly_name for a in assemblies]
    assembly_index = st.selectbox(
        "Assembly*", range(len(assemblies)), format_func=lambda i: assembly_labels[i], key=f"{key_prefix}assembly"
    )
    chosen_assembly = assemblies[assembly_index]

    version_labels = [v.version_name for v in chosen_assembly.versions]
    version_index = st.selectbox(
        "Version*",
        range(len(chosen_assembly.versions)),
        format_func=lambda i: version_labels[i],
        key=f"{key_prefix}version_{chosen_assembly.assembly_id}",
    )
    return chosen_assembly.versions[version_index].assembly_version_id


@st.dialog("Add batch", width="large")
def add_batch_dialog() -> None:
    with session_scope() as session:
        version_id = _version_picker(session, "batch_add_")
        if version_id is None:
            return
        batches = list_batch_choices(session)

    batch_code = st.text_input("Batch code*", key="batch_add_code")

    parent_options = ["No parent batch"] + [b.batch_code for b in batches]
    parent_index = st.selectbox("Parent batch", range(len(parent_options)), format_func=lambda i: parent_options[i], key="batch_add_parent")
    parent_id = batches[parent_index - 1].batch_id if parent_index > 0 else None

    expire = st.date_input(
        "Expire date", value=None, format=DATE_INPUT_FORMAT, key="batch_add_expire"
    )
    notes = st.text_area("Notes", key="batch_add_notes")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="batch_add_save"):
            if not batch_code.strip():
                st.error("Batch code is required.")
            else:
                with session_scope() as session:
                    create_batch(
                        session,
                        version_id,
                        batch_code.strip(),
                        parent_id=parent_id,
                        expire_date=expire if isinstance(expire, date) else None,
                        notes=notes.strip() or None,
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="batch_add_cancel"):
            st.rerun()


@st.dialog("Edit batch")
def edit_batch_dialog(batch_id: int) -> None:
    with session_scope() as session:
        batch = get_batch(session, batch_id)

    if batch is None:
        st.error("Batch not found.")
        return

    batch_code = st.text_input("Batch code*", value=batch.batch_code, key=f"batch_edit_{batch_id}_code")
    expire = st.date_input(
        "Expire date",
        value=batch.expire_date,
        format=DATE_INPUT_FORMAT,
        key=f"batch_edit_{batch_id}_expire",
    )
    notes = st.text_area("Notes", value=batch.notes or "", key=f"batch_edit_{batch_id}_notes")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key=f"batch_edit_{batch_id}_save"):
            if not batch_code.strip():
                st.error("Batch code is required.")
            else:
                with session_scope() as session:
                    update_batch(
                        session,
                        batch_id,
                        batch_code=batch_code.strip(),
                        expire_date=expire if isinstance(expire, date) else None,
                        notes=notes.strip() or None,
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"batch_edit_{batch_id}_cancel"):
            st.rerun()


@st.dialog("Add item to batch")
def add_batch_item_dialog(batch_id: int) -> None:
    with session_scope() as session:
        choices = list_all_item_choices(session)

    if not choices:
        st.warning("No items exist yet - add one on the Inventory page first.")
        return

    labels = [f"{sku} — {name}" for _, sku, name, _ in choices]
    choice_index = st.selectbox(
        "Product*", range(len(choices)), format_func=lambda i: labels[i], key="batch_item_add_product"
    )
    product_id = choices[choice_index][0]

    role = st.radio("Role", ["Consumed", "Produced"], horizontal=True, key="batch_item_add_role")
    magnitude = st.number_input(
        "Units", min_value=0.0001, step=0.01, value=1.0, format="%.4f", key="batch_item_add_units"
    )
    lot_number = st.text_input("Lot #", key="batch_item_add_lot")
    notes = st.text_area("Notes", key="batch_item_add_notes")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="batch_item_add_save"):
            units = -magnitude if role == "Consumed" else magnitude
            with session_scope() as session:
                add_batch_item(
                    session,
                    batch_id,
                    product_id,
                    units,
                    lot_number=lot_number.strip() or None,
                    notes=notes.strip() or None,
                )
            st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="batch_item_add_cancel"):
            st.rerun()


@st.dialog("Edit batch item")
def edit_batch_item_dialog(batch_item_id: int) -> None:
    with session_scope() as session:
        batch_item = get_batch_item(session, batch_item_id)
        if batch_item is None:
            st.error("Item not found.")
            return
        product_name = batch_item.product.name
        product_sku = batch_item.product.sku
        current_units = batch_item.units
        current_lot = batch_item.lot_number
        current_notes = batch_item.notes

    st.caption(f"{product_sku} — {product_name}")

    role = st.radio(
        "Role",
        ["Consumed", "Produced"],
        index=0 if current_units < 0 else 1,
        horizontal=True,
        key=f"batch_item_edit_{batch_item_id}_role",
    )
    magnitude = st.number_input(
        "Units",
        min_value=0.0001,
        step=0.01,
        value=abs(current_units),
        format="%.4f",
        key=f"batch_item_edit_{batch_item_id}_units",
    )
    lot_number = st.text_input(
        "Lot #", value=current_lot or "", key=f"batch_item_edit_{batch_item_id}_lot"
    )
    notes = st.text_area(
        "Notes", value=current_notes or "", key=f"batch_item_edit_{batch_item_id}_notes"
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button(
            "Save", type="primary", width="stretch", key=f"batch_item_edit_{batch_item_id}_save"
        ):
            units = -magnitude if role == "Consumed" else magnitude
            with session_scope() as session:
                update_batch_item(
                    session,
                    batch_item_id,
                    units=units,
                    lot_number=lot_number.strip() or None,
                    notes=notes.strip() or None,
                )
            st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"batch_item_edit_{batch_item_id}_cancel"):
            st.rerun()
