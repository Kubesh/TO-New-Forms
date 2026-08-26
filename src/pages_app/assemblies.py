import html

import streamlit as st

from src.db import session_scope
from src.services.assemblies import (
    add_version_item,
    create_assembly,
    create_version,
    delete_version_item,
    get_assembly,
    get_version,
    get_version_item,
    list_assemblies,
    update_assembly,
    update_version,
    update_version_item,
)
from src.services.items import list_all_item_choices

ASSEMBLY_CARD_CSS = """
<style>
.asm-card-link,
.asm-card-link:visited,
.asm-card-link:hover,
.asm-card-link * {
    color: inherit !important;
    text-decoration: none !important;
}
.asm-card-link {
    display: block;
}
.asm-card-list {
    padding-top: 0.75rem;
}
.asm-card {
    border: 2px solid #1A1712;
    border-radius: 0.625rem;
    padding: 0.85rem 1rem;
    margin-bottom: 0.75rem;
}
.asm-card-name {
    font-size: 1rem;
    font-weight: 700;
}
.asm-card-count {
    font-size: 0.8rem;
    opacity: 0.65;
    margin-top: 0.3rem;
}
</style>
"""


def assemblies_page() -> None:
    version_id_param = st.query_params.get("assembly_version_id")
    if version_id_param:
        try:
            version_id = int(version_id_param)
        except ValueError:
            version_id = None
        if version_id is not None:
            _render_version_detail(version_id)
            return

    assembly_id_param = st.query_params.get("assembly_id")
    if assembly_id_param:
        try:
            assembly_id = int(assembly_id_param)
        except ValueError:
            assembly_id = None
        if assembly_id is not None:
            _render_assembly_detail(assembly_id)
            return

    _render_list()


def _render_list() -> None:
    col_title, col_add = st.columns([3, 1])
    with col_title:
        st.title("Assemblies")
    with col_add:
        st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)
        if st.button("Add Assembly", width="stretch", key="asm_add"):
            add_assembly_dialog()

    query = st.text_input(
        "Search assemblies",
        placeholder="Search by name…",
        label_visibility="collapsed",
    )

    try:
        with session_scope() as session:
            assemblies = list_assemblies(session, query=query)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not assemblies:
        st.info("No assemblies yet - use Add Assembly to create one.")
        return

    cards_html = "".join(_card_html(assembly) for assembly in assemblies)
    st.markdown(
        f'{ASSEMBLY_CARD_CSS}<div class="asm-card-list">{cards_html}</div>',
        unsafe_allow_html=True,
    )


def _card_html(assembly) -> str:
    name = html.escape(assembly.assembly_name)
    version_count = len(assembly.versions)
    count_label = f"{version_count} version{'s' if version_count != 1 else ''}"
    return (
        f'<a class="asm-card-link" href="?assembly_id={assembly.assembly_id}" target="_self">'
        f'<div class="asm-card">'
        f'<div class="asm-card-name">{name}</div>'
        f'<div class="asm-card-count">{count_label}</div>'
        "</div></a>"
    )


def _render_assembly_detail(assembly_id: int) -> None:
    try:
        with session_scope() as session:
            assembly = get_assembly(session, assembly_id)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if assembly is None:
        st.warning("Assembly not found.")
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
        if st.button("Edit assembly", width="stretch"):
            edit_assembly_dialog(assembly.assembly_id)

    st.header(assembly.assembly_name)
    if assembly.notes:
        st.write(assembly.notes)

    st.subheader("Versions")
    if st.button("+ Add Version", key="asm_add_version"):
        add_version_dialog(assembly.assembly_id)

    if not assembly.versions:
        st.caption("No versions yet.")
        return

    versions_html = "".join(_version_card_html(assembly_id, v) for v in assembly.versions)
    st.markdown(
        f'{ASSEMBLY_CARD_CSS}<div class="asm-card-list">{versions_html}</div>',
        unsafe_allow_html=True,
    )


def _version_card_html(assembly_id: int, version) -> str:
    name = html.escape(version.version_name)
    item_count = len(version.items)
    count_label = f"{item_count} line item{'s' if item_count != 1 else ''}"
    return (
        f'<a class="asm-card-link" '
        f'href="?assembly_id={assembly_id}&assembly_version_id={version.assembly_version_id}" '
        f'target="_self">'
        f'<div class="asm-card">'
        f'<div class="asm-card-name">{name}</div>'
        f'<div class="asm-card-count">{count_label}</div>'
        "</div></a>"
    )


def _render_version_detail(assembly_version_id: int) -> None:
    try:
        with session_scope() as session:
            version = get_version(session, assembly_version_id)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if version is None:
        st.warning("Version not found.")
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
        return

    col_back, col_edit = st.columns([3, 1])
    with col_back:
        if st.button(f"← Back to {version.assembly.assembly_name}"):
            st.query_params.clear()
            st.query_params["assembly_id"] = str(version.assembly_id)
            st.rerun()
    with col_edit:
        if st.button("Edit version", width="stretch"):
            edit_version_dialog(version.assembly_version_id)

    st.caption(version.assembly.assembly_name)
    st.header(version.version_name)
    if version.notes:
        st.write(version.notes)

    st.subheader("Items")
    if st.button("+ Add Item", key="asm_add_item"):
        add_version_item_dialog(version.assembly_version_id)

    if not version.items:
        st.caption("No items in this version yet.")
        return

    header_cols = st.columns([3, 1.5, 1, 1])
    for col, label in zip(header_cols, ["Product", "Role", "Amount", ""]):
        with col:
            st.caption(label)

    for version_item in version.items:
        row_cols = st.columns([3, 1.5, 1, 1])
        with row_cols[0]:
            st.markdown(
                f'<a href="/items?item_id={version_item.product.item_id}" target="_self" '
                f'style="color: inherit; text-decoration: none;">'
                f"<strong>{html.escape(version_item.product.name)}</strong> "
                f"<span style='opacity:0.6;'>({html.escape(version_item.product.sku)})</span>"
                f"</a>",
                unsafe_allow_html=True,
            )
        with row_cols[1]:
            if version_item.amount < 0:
                st.markdown("<span style='color:#b91c1c;'>Consumed</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#059669;'>Produced</span>", unsafe_allow_html=True)
        with row_cols[2]:
            st.write(f"{version_item.amount:+d}")
        with row_cols[3]:
            action_cols = st.columns(2)
            with action_cols[0]:
                if st.button(
                    "✎", key=f"asmv_item_edit_{version_item.assembly_version_item_id}", help="Edit"
                ):
                    edit_version_item_dialog(version_item.assembly_version_item_id)
            with action_cols[1]:
                if st.button(
                    "✕", key=f"asmv_item_del_{version_item.assembly_version_item_id}", help="Remove"
                ):
                    with session_scope() as session:
                        delete_version_item(session, version_item.assembly_version_item_id)
                    st.rerun()


@st.dialog("Add assembly")
def add_assembly_dialog() -> None:
    name = st.text_input("Assembly name*", key="asm_add_name")
    notes = st.text_area("Notes", key="asm_add_notes")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="asm_add_save"):
            if not name.strip():
                st.error("Assembly name is required.")
            else:
                with session_scope() as session:
                    create_assembly(session, name.strip(), notes=notes.strip() or None)
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="asm_add_cancel"):
            st.rerun()


@st.dialog("Edit assembly")
def edit_assembly_dialog(assembly_id: int) -> None:
    with session_scope() as session:
        assembly = get_assembly(session, assembly_id)

    if assembly is None:
        st.error("Assembly not found.")
        return

    name = st.text_input(
        "Assembly name*", value=assembly.assembly_name, key=f"asm_edit_{assembly_id}_name"
    )
    notes = st.text_area("Notes", value=assembly.notes or "", key=f"asm_edit_{assembly_id}_notes")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key=f"asm_edit_{assembly_id}_save"):
            if not name.strip():
                st.error("Assembly name is required.")
            else:
                with session_scope() as session:
                    update_assembly(
                        session, assembly_id, assembly_name=name.strip(), notes=notes.strip() or None
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"asm_edit_{assembly_id}_cancel"):
            st.rerun()


@st.dialog("Add version")
def add_version_dialog(assembly_id: int) -> None:
    version_name = st.text_input("Version name*", key="asmv_add_name")
    notes = st.text_area("Notes", key="asmv_add_notes")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="asmv_add_save"):
            if not version_name.strip():
                st.error("Version name is required.")
            else:
                with session_scope() as session:
                    create_version(
                        session, assembly_id, version_name.strip(), notes=notes.strip() or None
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="asmv_add_cancel"):
            st.rerun()


@st.dialog("Edit version")
def edit_version_dialog(assembly_version_id: int) -> None:
    with session_scope() as session:
        version = get_version(session, assembly_version_id)

    if version is None:
        st.error("Version not found.")
        return

    version_name = st.text_input(
        "Version name*", value=version.version_name, key=f"asmv_edit_{assembly_version_id}_name"
    )
    notes = st.text_area(
        "Notes", value=version.notes or "", key=f"asmv_edit_{assembly_version_id}_notes"
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button(
            "Save", type="primary", width="stretch", key=f"asmv_edit_{assembly_version_id}_save"
        ):
            if not version_name.strip():
                st.error("Version name is required.")
            else:
                with session_scope() as session:
                    update_version(
                        session,
                        assembly_version_id,
                        version_name=version_name.strip(),
                        notes=notes.strip() or None,
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"asmv_edit_{assembly_version_id}_cancel"):
            st.rerun()


@st.dialog("Add item to version")
def add_version_item_dialog(assembly_version_id: int) -> None:
    with session_scope() as session:
        choices = list_all_item_choices(session)

    if not choices:
        st.warning("No items exist yet - add one on the Inventory page first.")
        return

    labels = [f"{sku} — {name}" for _, sku, name, _ in choices]
    choice_index = st.selectbox(
        "Product*", range(len(choices)), format_func=lambda i: labels[i], key="asmv_item_add_product"
    )
    product_id = choices[choice_index][0]

    role = st.radio("Role", ["Consumed", "Produced"], horizontal=True, key="asmv_item_add_role")
    magnitude = st.number_input(
        "Amount", min_value=1, step=1, value=1, key="asmv_item_add_amount"
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="asmv_item_add_save"):
            amount = -int(magnitude) if role == "Consumed" else int(magnitude)
            with session_scope() as session:
                add_version_item(session, assembly_version_id, product_id, amount)
            st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="asmv_item_add_cancel"):
            st.rerun()


@st.dialog("Edit version item")
def edit_version_item_dialog(assembly_version_item_id: int) -> None:
    with session_scope() as session:
        version_item = get_version_item(session, assembly_version_item_id)
        if version_item is None:
            st.error("Item not found.")
            return
        product_name = version_item.product.name
        product_sku = version_item.product.sku
        current_amount = version_item.amount

    st.caption(f"{product_sku} — {product_name}")

    role = st.radio(
        "Role",
        ["Consumed", "Produced"],
        index=0 if current_amount < 0 else 1,
        horizontal=True,
        key=f"asmv_item_edit_{assembly_version_item_id}_role",
    )
    magnitude = st.number_input(
        "Amount",
        min_value=1,
        step=1,
        value=abs(current_amount),
        key=f"asmv_item_edit_{assembly_version_item_id}_amount",
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button(
            "Save",
            type="primary",
            width="stretch",
            key=f"asmv_item_edit_{assembly_version_item_id}_save",
        ):
            amount = -int(magnitude) if role == "Consumed" else int(magnitude)
            with session_scope() as session:
                update_version_item(session, assembly_version_item_id, amount=amount)
            st.rerun()
    with col_cancel:
        if st.button(
            "Cancel", width="stretch", key=f"asmv_item_edit_{assembly_version_item_id}_cancel"
        ):
            st.rerun()
