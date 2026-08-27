import html

import streamlit as st

from src.db import session_scope
from src.services.assemblies import (
    add_version_item,
    create_assembly,
    create_version,
    delete_assembly,
    delete_version,
    delete_version_item,
    get_assembly,
    get_descendant_version_ids,
    get_lineage_chains,
    get_version,
    get_version_item,
    list_all_version_choices,
    list_assemblies,
    set_active_version,
    update_assembly,
    update_version,
    update_version_item,
)
from src.services.items import list_all_item_choices


def _format_datetime(value) -> str:
    return value.strftime("%m/%d/%y %-I:%M %p") if value else "—"


def _format_amount(amount) -> str:
    """+/-26.2 rather than +/-26.2000 - trims the trailing zeros a fixed
    4-decimal-place Numeric column always renders with, without touching
    the integer part (a naive rstrip("0") would mangle a whole number like
    100.0000 into 1)."""
    text = f"{amount:.4f}".rstrip("0").rstrip(".") or "0"
    return text if text.startswith("-") else f"+{text}"


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
.asm-card-active {
    border-color: #059669;
}
.asm-badge-active {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: #059669;
    background: rgba(5, 150, 105, 0.12);
    border-radius: 0.3rem;
    padding: 0.1rem 0.4rem;
    margin-top: 0.3rem;
}
.lineage-chain {
    margin-bottom: 1.5rem;
    max-width: 420px;
}
.lineage-chain .asm-card {
    margin-bottom: 0;
}
.lineage-chain .asm-card-current {
    border-color: #F4591A;
}
.lineage-arrow {
    text-align: center;
    font-size: 0.75rem;
    opacity: 0.6;
    padding: 0.35rem 0;
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
    active_version = next(
        (v for v in assembly.versions if v.assembly_version_id == assembly.active_version_id), None
    )
    if active_version is not None:
        count_label += f" · Active: {html.escape(active_version.version_name)}"
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

    col_back, col_edit, col_delete = st.columns([2, 1, 1])
    with col_back:
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
    with col_edit:
        if st.button("Edit assembly", width="stretch"):
            edit_assembly_dialog(assembly.assembly_id)
    with col_delete:
        if st.button("Delete assembly", width="stretch"):
            delete_assembly_confirm_dialog(assembly.assembly_id, len(assembly.versions))

    st.header(assembly.assembly_name)
    if assembly.notes:
        st.write(assembly.notes)

    tab_versions, tab_lineage = st.tabs(["Versions", "Lineage"])

    with tab_versions:
        if st.button("+ Add Version", key="asm_add_version"):
            add_version_dialog(assembly.assembly_id)

        if not assembly.versions:
            st.caption("No versions yet.")
        else:
            versions_html = "".join(
                _version_card_html(assembly_id, v, assembly.active_version_id)
                for v in assembly.versions
            )
            st.markdown(
                f'{ASSEMBLY_CARD_CSS}<div class="asm-card-list">{versions_html}</div>',
                unsafe_allow_html=True,
            )

    with tab_lineage:
        _render_lineage_tab(assembly_id)


def _lineage_chain_html(chain: list[dict], current_assembly_id: int) -> str:
    parts = []
    for i, node in enumerate(chain):
        if i > 0:
            parts.append('<div class="lineage-arrow">↓ replaced by</div>')
        card_class = "asm-card"
        if node["assembly_id"] == current_assembly_id:
            card_class += " asm-card-current"
        version_label = html.escape(node["version_name"])
        assembly_label = html.escape(node["assembly_name"])
        parts.append(
            f'<a class="asm-card-link" '
            f'href="?assembly_id={node["assembly_id"]}&assembly_version_id={node["assembly_version_id"]}" '
            f'target="_self">'
            f'<div class="{card_class}">'
            f'<div class="asm-card-name">{version_label}</div>'
            f'<div class="asm-card-count">{assembly_label}</div>'
            "</div></a>"
        )
    return f'<div class="lineage-chain">{"".join(parts)}</div>'


def _render_lineage_tab(assembly_id: int) -> None:
    with session_scope() as session:
        chains = get_lineage_chains(session, assembly_id)

    if not chains:
        st.caption(
            'No version replacements recorded yet - set "Replaces version" when adding '
            "or editing a version."
        )
        return

    chains_html = "".join(_lineage_chain_html(chain, assembly_id) for chain in chains)
    st.markdown(f"{ASSEMBLY_CARD_CSS}{chains_html}", unsafe_allow_html=True)


def _version_card_html(assembly_id: int, version, active_version_id: int | None) -> str:
    name = html.escape(version.version_name)
    item_count = len(version.items)
    count_label = f"{item_count} line item{'s' if item_count != 1 else ''}"
    is_active = version.assembly_version_id == active_version_id
    card_class = "asm-card asm-card-active" if is_active else "asm-card"
    badge = '<div class="asm-badge-active">Active</div>' if is_active else ""
    return (
        f'<a class="asm-card-link" '
        f'href="?assembly_id={assembly_id}&assembly_version_id={version.assembly_version_id}" '
        f'target="_self">'
        f'<div class="{card_class}">'
        f'<div class="asm-card-name">{name}</div>'
        f'<div class="asm-card-count">{count_label}</div>'
        f"{badge}"
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

    is_active = version.assembly_version_id == version.assembly.active_version_id

    col_back, col_active, col_edit, col_delete = st.columns([2, 1, 1, 1])
    with col_back:
        if st.button(f"← Back to {version.assembly.assembly_name}"):
            st.query_params.clear()
            st.query_params["assembly_id"] = str(version.assembly_id)
            st.rerun()
    with col_active:
        if is_active:
            st.markdown(
                f'{ASSEMBLY_CARD_CSS}<div style="text-align:center; padding-top:0.4rem;">'
                '<div class="asm-badge-active">Active</div></div>',
                unsafe_allow_html=True,
            )
        elif st.button("Set as active", width="stretch"):
            with session_scope() as session:
                set_active_version(session, version.assembly_id, version.assembly_version_id)
            st.rerun()
    with col_edit:
        if st.button("Edit version", width="stretch"):
            edit_version_dialog(version.assembly_version_id)
    with col_delete:
        if st.button("Delete version", width="stretch"):
            delete_version_confirm_dialog(version.assembly_version_id, version.assembly_id)

    st.caption(version.assembly.assembly_name)
    st.header(version.version_name)
    if version.notes:
        st.write(version.notes)

    st.caption(
        f"Created {_format_datetime(version.created_at)} · "
        f"Updated {_format_datetime(version.updated_at)}"
    )

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
            st.write(_format_amount(version_item.amount))
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


@st.dialog("Delete assembly", width="small")
def delete_assembly_confirm_dialog(assembly_id: int, version_count: int) -> None:
    st.warning(
        f"Delete this assembly and its {version_count} "
        f"version{'s' if version_count != 1 else ''}? This can't be undone."
    )
    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button(
            "Delete", type="primary", width="stretch", key=f"asm_delete_{assembly_id}_confirm"
        ):
            with session_scope() as session:
                error = delete_assembly(session, assembly_id)
            if error:
                st.error(error)
            else:
                st.query_params.clear()
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"asm_delete_{assembly_id}_cancel"):
            st.rerun()


def _replaces_picker(
    choices: list[tuple[int, str, str]], key: str, current_id: int | None
) -> int | None:
    labels = ["None"] + [f"{a} — {v}" for _, a, v in choices]
    ids: list[int | None] = [None] + [c[0] for c in choices]
    index = ids.index(current_id) if current_id in ids else 0
    picked = st.selectbox(
        "Replaces version",
        range(len(labels)),
        format_func=lambda i: labels[i],
        index=index,
        key=key,
        help="The version this one took over for, if any - shows up in the Lineage tab.",
    )
    return ids[picked]


@st.dialog("Add version")
def add_version_dialog(assembly_id: int) -> None:
    with session_scope() as session:
        choices = list_all_version_choices(session)

    version_name = st.text_input("Version name*", key="asmv_add_name")
    notes = st.text_area("Notes", key="asmv_add_notes")
    replaces_version_id = _replaces_picker(choices, key="asmv_add_replaces", current_id=None)

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="asmv_add_save"):
            if not version_name.strip():
                st.error("Version name is required.")
            else:
                with session_scope() as session:
                    create_version(
                        session,
                        assembly_id,
                        version_name.strip(),
                        notes=notes.strip() or None,
                        replaces_version_id=replaces_version_id,
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
        current_replaces_id = version.replaces_version_id
        excluded_ids = get_descendant_version_ids(session, assembly_version_id)
        excluded_ids.add(assembly_version_id)
        choices = [
            c for c in list_all_version_choices(session) if c[0] not in excluded_ids
        ]

    version_name = st.text_input(
        "Version name*", value=version.version_name, key=f"asmv_edit_{assembly_version_id}_name"
    )
    notes = st.text_area(
        "Notes", value=version.notes or "", key=f"asmv_edit_{assembly_version_id}_notes"
    )
    replaces_version_id = _replaces_picker(
        choices, key=f"asmv_edit_{assembly_version_id}_replaces", current_id=current_replaces_id
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
                        replaces_version_id=replaces_version_id,
                    )
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"asmv_edit_{assembly_version_id}_cancel"):
            st.rerun()


@st.dialog("Delete version", width="small")
def delete_version_confirm_dialog(assembly_version_id: int, assembly_id: int) -> None:
    st.warning("Delete this version and its items? This can't be undone.")
    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button(
            "Delete",
            type="primary",
            width="stretch",
            key=f"asmv_delete_{assembly_version_id}_confirm",
        ):
            with session_scope() as session:
                error = delete_version(session, assembly_version_id)
            if error:
                st.error(error)
            else:
                st.query_params.clear()
                st.query_params["assembly_id"] = str(assembly_id)
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"asmv_delete_{assembly_version_id}_cancel"):
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
        "Amount",
        min_value=0.0001,
        step=0.01,
        value=1.0,
        format="%.4f",
        key="asmv_item_add_amount",
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="asmv_item_add_save"):
            amount = -magnitude if role == "Consumed" else magnitude
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
        min_value=0.0001,
        step=0.01,
        value=float(abs(current_amount)),
        format="%.4f",
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
            amount = -magnitude if role == "Consumed" else magnitude
            with session_scope() as session:
                update_version_item(session, assembly_version_item_id, amount=amount)
            st.rerun()
    with col_cancel:
        if st.button(
            "Cancel", width="stretch", key=f"asmv_item_edit_{assembly_version_item_id}_cancel"
        ):
            st.rerun()
