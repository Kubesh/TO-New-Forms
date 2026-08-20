import html

import streamlit as st

from src.db import session_scope
from src.services.customers import (
    STORE_KEY_RANGE_END,
    STORE_KEY_RANGE_START,
    count_customers,
    create_customer,
    get_customer,
    get_duplicate_customer_names,
    list_customer_choices,
    list_customer_types,
    list_distinct_chain_names,
    list_distinct_shipping_states,
    search_customers,
    update_customer,
)
from src.pages_app.purchase_orders import create_po_dialog, render_po_table
from src.services.order_types import list_order_type_choices
from src.services.purchase_orders import (
    get_non_voided_po_counts,
    get_po_line_item_stats,
    list_purchase_orders_for_customer,
)

ADDRESS_FIELDS = (
    "address_line1",
    "address_line2",
    "city",
    "state",
    "postal_code",
    "country",
)

PAGE_SIZE = 25

CARD_CSS = """
<style>
.customer-card-link,
.customer-card-link:visited,
.customer-card-link:hover,
.customer-card-link * {
    color: inherit !important;
    text-decoration: none !important;
}
.customer-card-list {
    padding-top: 0.75rem;
}
.customer-card-link {
    display: block;
    margin-bottom: 0.75rem;
}
.customer-card {
    position: relative;
    border: 2px solid #1A1712;
    border-radius: 0.625rem;
    padding: 1rem 1.25rem;
    width: 100%;
    box-sizing: border-box;
    transition: border-color 0.15s ease;
}
.customer-card-po-badge {
    position: absolute;
    top: 1rem;
    right: 1.25rem;
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    background: #F4591A;
    color: #FFFFFF !important;
}
.customer-card-link:hover .customer-card {
    border-color: #F4591A;
}
.customer-card-has-parent {
    border-color: #F4591A;
    border-width: 2px;
}
.customer-card-link:hover .customer-card-has-parent {
    border-color: #D94A0E;
}
.customer-card-top {
    display: flex;
    gap: 0.4rem;
    margin-bottom: 0.35rem;
}
.customer-card-badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    background: rgba(128, 128, 128, 0.18);
    color: inherit;
}
.customer-card-badge-dup {
    background: rgba(255, 165, 0, 0.25);
    color: #b45309 !important;
}
.customer-card-parent {
    font-size: 0.85rem;
    opacity: 0.7;
    margin-bottom: 0.1rem;
}
.customer-card-name {
    font-size: 1.25rem;
    font-weight: 700;
}
.customer-card-location {
    margin-top: 0.25rem;
    opacity: 0.85;
}
</style>
"""

def customers_page() -> None:
    st.title("Customers")

    customer_id_param = st.query_params.get("customer_id")
    if customer_id_param:
        try:
            customer_id = int(customer_id_param)
        except ValueError:
            customer_id = None
        if customer_id is not None:
            _render_detail(customer_id)
            return

    _render_list()


def _render_list() -> None:
    col_search, col_add = st.columns([3, 1])
    with col_search:
        query = st.text_input(
            "Search customers",
            placeholder="Search by name…",
            label_visibility="collapsed",
        )
    with col_add:
        if st.button("Add customer", width="stretch"):
            add_customer_dialog()

    try:
        with session_scope() as session:
            type_choices = list_customer_types(session)
            state_choices = list_distinct_shipping_states(session)
            chain_choices = list_distinct_chain_names(session)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    col_type, col_state, col_chain, col_ordered, col_archived = st.columns([1, 1, 1, 1, 1])
    with col_type:
        type_choice = st.selectbox("Account type", ["All types"] + [t.name for t in type_choices])
    with col_state:
        state_choice = st.selectbox("Shipping state", ["All states"] + state_choices)
    with col_chain:
        chain_choice = st.selectbox("Chain name", ["All chains"] + chain_choices)
    with col_ordered:
        st.markdown("<div style='height: 1.85rem'></div>", unsafe_allow_html=True)
        ordered_only = st.checkbox("Ordered", help="Only show customers who have ever placed a purchase order.")
    with col_archived:
        st.markdown("<div style='height: 1.85rem'></div>", unsafe_allow_html=True)
        show_archived = st.checkbox("Archived", help="Show archived customers instead of active ones.")

    type_id = None
    if type_choice != "All types":
        type_id = next(t.customer_type_id for t in type_choices if t.name == type_choice)
    shipping_state = None if state_choice == "All states" else state_choice
    chain_name = None if chain_choice == "All chains" else chain_choice
    has_ordered = True if ordered_only else None

    filters_key = (query, type_id, shipping_state, chain_name, has_ordered, show_archived)
    if st.session_state.get("customer_filters_key") != filters_key:
        st.session_state["customer_filters_key"] = filters_key
        st.session_state["customer_page"] = 1
    page = st.session_state.get("customer_page", 1)

    try:
        with session_scope() as session:
            total = count_customers(
                session, query, type_id, shipping_state, chain_name, has_ordered, show_archived
            )
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(max(page, 1), total_pages)
            st.session_state["customer_page"] = page

            if total:
                customers = search_customers(
                    session,
                    query,
                    type_id,
                    shipping_state,
                    chain_name,
                    has_ordered,
                    show_archived,
                    limit=PAGE_SIZE,
                    offset=(page - 1) * PAGE_SIZE,
                )
                duplicate_names = get_duplicate_customer_names(session)
                po_counts = get_non_voided_po_counts(
                    session, [c.customer_id for c in customers]
                )
            else:
                customers = []
                duplicate_names = set()
                po_counts = {}
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not customers:
        st.info("No customers found.")
        return

    cards_html = "".join(
        _card_html(
            customer,
            customer.customer_name in duplicate_names,
            po_counts.get(customer.customer_id, 0),
        )
        for customer in customers
    )
    st.markdown(
        f'{CARD_CSS}<div class="customer-card-list">{cards_html}</div>',
        unsafe_allow_html=True,
    )

    _render_pagination(page, total_pages, total)


def _render_pagination(page: int, total_pages: int, total: int) -> None:
    start = (page - 1) * PAGE_SIZE + 1
    end = min(page * PAGE_SIZE, total)
    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("← Previous", disabled=page <= 1, width="stretch"):
            st.session_state["customer_page"] = page - 1
            st.rerun()
    with col_info:
        st.markdown(
            f'<div style="text-align:center; padding-top: 0.4rem;">'
            f"Showing {start}–{end} of {total} · Page {page} of {total_pages}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button("Next →", disabled=page >= total_pages, width="stretch"):
            st.session_state["customer_page"] = page + 1
            st.rerun()


def _card_html(customer, is_duplicate: bool, po_count: int = 0) -> str:
    name = html.escape(customer.customer_name)
    type_name = html.escape(customer.customer_type.name) if customer.customer_type else None
    parent_name = html.escape(customer.parent.customer_name) if customer.parent else None

    city = customer.billing_city or customer.shipping_city
    state = customer.billing_state or customer.shipping_state
    location = html.escape(", ".join(filter(None, [city, state])))

    card_classes = "customer-card"
    if customer.parent_id:
        card_classes += " customer-card-has-parent"

    top_badges = []
    if type_name:
        top_badges.append(f'<span class="customer-card-badge">{type_name}</span>')
    if is_duplicate:
        top_badges.append(
            '<span class="customer-card-badge customer-card-badge-dup">Duplicate name</span>'
        )

    parts = [
        f'<a class="customer-card-link" href="?customer_id={customer.customer_id}" target="_self">',
        f'<div class="{card_classes}">',
    ]
    if po_count:
        label = "1 PO" if po_count == 1 else f"{po_count} POs"
        parts.append(f'<div class="customer-card-po-badge">{label}</div>')
    if top_badges:
        parts.append(f'<div class="customer-card-top">{"".join(top_badges)}</div>')
    if parent_name:
        parts.append(f'<div class="customer-card-parent">{parent_name}</div>')
    parts.append(f'<div class="customer-card-name">{name}</div>')
    if location:
        parts.append(f'<div class="customer-card-location">{location}</div>')
    parts.append("</div></a>")
    return "".join(parts)


def _render_detail(customer_id: int) -> None:
    with session_scope() as session:
        customer = get_customer(session, customer_id)
        duplicate_names = get_duplicate_customer_names(session)
        purchase_orders = (
            list_purchase_orders_for_customer(session, customer_id) if customer else []
        )
        po_stats = get_po_line_item_stats(session, [po.po_id for po in purchase_orders])

    if not customer:
        st.warning("Customer not found.")
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
        return

    if st.session_state.pop("store_key_range_exhausted", False):
        st.warning(
            f"This customer was created without a store key - the "
            f"{STORE_KEY_RANGE_START}-{STORE_KEY_RANGE_END - 1} range is full."
        )

    col_back, col_edit, col_archive = st.columns([2, 1, 1])
    with col_back:
        if st.button("← Back to list"):
            st.query_params.clear()
            st.rerun()
    with col_edit:
        if st.button("Edit customer", width="stretch"):
            edit_customer_dialog(customer.customer_id)
    with col_archive:
        archive_label = "Unarchive customer" if customer.archived else "Archive customer"
        if st.button(archive_label, width="stretch", key="archive_customer_btn"):
            with session_scope() as session:
                update_customer(session, customer.customer_id, archived=not customer.archived)
            st.rerun()

    st.header(customer.customer_name)
    st.caption(customer.customer_type.name if customer.customer_type else "No type")
    if customer.archived:
        st.badge("Archived", color="gray")
    if customer.customer_name in duplicate_names:
        st.badge("Duplicate name - another customer shares this name", color="orange")
    if customer.parent:
        st.write(f"Parent account: **{customer.parent.customer_name}**")
    if customer.phone_number:
        st.write(f"Phone: {customer.phone_number}")
    if customer.store_key is not None:
        st.caption(f"Previous store key: {customer.store_key}")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Billing")
        _render_address(customer, "billing")
    with col2:
        st.subheader("Shipping")
        _render_address(customer, "shipping")

    st.subheader("Contacts")
    if customer.contacts:
        for contact in customer.contacts:
            with st.container(border=True):
                st.write(f"**{contact.contact_name}**")
                if contact.contact_phone:
                    st.write(contact.contact_phone)
                if contact.contact_notes:
                    st.caption(contact.contact_notes)
    else:
        st.write("No contacts on file.")

    if customer.children:
        st.subheader("Sub-accounts")
        for child in customer.children:
            st.write(f"- {child.customer_name}")

    col_po_header, col_po_create = st.columns([3, 1])
    with col_po_header:
        st.subheader("Purchase Orders")
    with col_po_create:
        if st.button("Create purchase order", width="stretch", key="create_po_btn"):
            create_po_dialog(customer.customer_id)
    if purchase_orders:
        render_po_table(purchase_orders, po_stats, href_base="/purchase-orders")
    else:
        st.write("No purchase orders on file.")


def _render_address(customer, prefix: str) -> None:
    values = {field: getattr(customer, f"{prefix}_{field}") for field in ADDRESS_FIELDS}

    if not any(values.values()):
        st.write("Not on file.")
        return

    if values["address_line1"]:
        st.write(values["address_line1"])
    if values["address_line2"]:
        st.write(values["address_line2"])

    city_state = ", ".join(filter(None, [values["city"], values["state"]]))
    city_state_zip = " ".join(filter(None, [city_state, values["postal_code"]]))
    if city_state_zip:
        st.write(city_state_zip)

    if values["country"]:
        st.write(values["country"])


def _render_customer_form(
    default: dict, type_choices, parent_choices, order_type_choices, key_prefix: str
) -> dict:
    customer_name = st.text_input(
        "Customer name*",
        value=default.get("customer_name", ""),
        max_chars=255,
        key=f"{key_prefix}_customer_name",
    )

    type_names = ["No type"] + [name for _, name in type_choices]
    type_ids = [None] + [type_id for type_id, _ in type_choices]
    try:
        type_index = type_ids.index(default.get("customer_type_id"))
    except ValueError:
        type_index = 0
    type_choice = st.selectbox(
        "Customer type", type_names, index=type_index, key=f"{key_prefix}_customer_type"
    )
    customer_type_id = type_ids[type_names.index(type_choice)]

    order_type_names = ["No override (use customer type default)"] + [
        name for _, name in order_type_choices
    ]
    order_type_ids = [None] + [order_type_id for order_type_id, _ in order_type_choices]
    try:
        order_type_index = order_type_ids.index(default.get("default_order_type_id"))
    except ValueError:
        order_type_index = 0
    order_type_choice = st.selectbox(
        "Default order type",
        order_type_names,
        index=order_type_index,
        key=f"{key_prefix}_default_order_type",
        help="New POs for this customer start with this order type. Leave unset to fall "
        "back to Direct, or Distributor for distributor-type customers.",
    )
    default_order_type_id = order_type_ids[order_type_names.index(order_type_choice)]

    parent_names = ["No parent"] + [name for _, name in parent_choices]
    parent_ids = [None] + [parent_id for parent_id, _ in parent_choices]
    try:
        parent_index = parent_ids.index(default.get("parent_id"))
    except ValueError:
        parent_index = 0
    parent_choice = st.selectbox(
        "Parent account", parent_names, index=parent_index, key=f"{key_prefix}_parent"
    )
    parent_id = parent_ids[parent_names.index(parent_choice)]

    phone_number = st.text_input(
        "Phone number",
        value=default.get("phone_number") or "",
        max_chars=25,
        key=f"{key_prefix}_phone_number",
    )

    notes = st.text_input(
        "Notes", value=default.get("notes") or "", max_chars=100, key=f"{key_prefix}_notes"
    )

    st.markdown("**Shipping address**")
    shipping_address_line1 = st.text_input(
        "Address line 1",
        value=default.get("shipping_address_line1") or "",
        max_chars=255,
        key=f"{key_prefix}_shipping_address_line1",
    )
    shipping_address_line2 = st.text_input(
        "Address line 2",
        value=default.get("shipping_address_line2") or "",
        max_chars=255,
        key=f"{key_prefix}_shipping_address_line2",
    )
    shipping_city = st.text_input(
        "City",
        value=default.get("shipping_city") or "",
        max_chars=120,
        key=f"{key_prefix}_shipping_city",
    )
    shipping_state = st.text_input(
        "State",
        value=default.get("shipping_state") or "",
        max_chars=120,
        key=f"{key_prefix}_shipping_state",
    )
    shipping_postal_code = st.text_input(
        "Postal code",
        value=default.get("shipping_postal_code") or "",
        max_chars=20,
        key=f"{key_prefix}_shipping_postal_code",
    )
    shipping_country = st.text_input(
        "Country",
        value=default.get("shipping_country") or "",
        max_chars=120,
        key=f"{key_prefix}_shipping_country",
    )

    shipping_fields = dict(
        address_line1=shipping_address_line1.strip() or None,
        address_line2=shipping_address_line2.strip() or None,
        city=shipping_city.strip() or None,
        state=shipping_state.strip() or None,
        postal_code=shipping_postal_code.strip() or None,
        country=shipping_country.strip() or None,
    )

    billing_default_tuple = tuple(default.get(f"billing_{f}") for f in ADDRESS_FIELDS)
    shipping_default_tuple = tuple(default.get(f"shipping_{f}") for f in ADDRESS_FIELDS)
    same_as_shipping_default = billing_default_tuple == shipping_default_tuple

    same_as_shipping = st.checkbox(
        "Billing address same as shipping",
        value=same_as_shipping_default,
        key=f"{key_prefix}_billing_same_as_shipping",
    )

    if same_as_shipping:
        billing_fields = dict(shipping_fields)
    else:
        st.markdown("**Billing address**")
        billing_address_line1 = st.text_input(
            "Address line 1",
            value=default.get("billing_address_line1") or "",
            max_chars=255,
            key=f"{key_prefix}_billing_address_line1",
        )
        billing_address_line2 = st.text_input(
            "Address line 2",
            value=default.get("billing_address_line2") or "",
            max_chars=255,
            key=f"{key_prefix}_billing_address_line2",
        )
        billing_city = st.text_input(
            "City",
            value=default.get("billing_city") or "",
            max_chars=120,
            key=f"{key_prefix}_billing_city",
        )
        billing_state = st.text_input(
            "State",
            value=default.get("billing_state") or "",
            max_chars=120,
            key=f"{key_prefix}_billing_state",
        )
        billing_postal_code = st.text_input(
            "Postal code",
            value=default.get("billing_postal_code") or "",
            max_chars=20,
            key=f"{key_prefix}_billing_postal_code",
        )
        billing_country = st.text_input(
            "Country",
            value=default.get("billing_country") or "",
            max_chars=120,
            key=f"{key_prefix}_billing_country",
        )
        billing_fields = dict(
            address_line1=billing_address_line1.strip() or None,
            address_line2=billing_address_line2.strip() or None,
            city=billing_city.strip() or None,
            state=billing_state.strip() or None,
            postal_code=billing_postal_code.strip() or None,
            country=billing_country.strip() or None,
        )

    return dict(
        customer_name=customer_name.strip(),
        customer_type_id=customer_type_id,
        default_order_type_id=default_order_type_id,
        parent_id=parent_id,
        phone_number=phone_number.strip() or None,
        notes=notes.strip() or None,
        billing_address_line1=billing_fields["address_line1"],
        billing_address_line2=billing_fields["address_line2"],
        billing_city=billing_fields["city"],
        billing_state=billing_fields["state"],
        billing_postal_code=billing_fields["postal_code"],
        billing_country=billing_fields["country"],
        shipping_address_line1=shipping_fields["address_line1"],
        shipping_address_line2=shipping_fields["address_line2"],
        shipping_city=shipping_fields["city"],
        shipping_state=shipping_fields["state"],
        shipping_postal_code=shipping_fields["postal_code"],
        shipping_country=shipping_fields["country"],
    )


@st.dialog("Edit customer", width="large")
def edit_customer_dialog(customer_id: int) -> None:
    with session_scope() as session:
        customer = get_customer(session, customer_id)
        type_choices = [(t.customer_type_id, t.name) for t in list_customer_types(session)]
        order_type_choices = list_order_type_choices(session)
        parent_choices = list_customer_choices(session, exclude_customer_id=customer_id)

    if not customer:
        st.error("Customer not found.")
        return

    default = dict(
        customer_name=customer.customer_name,
        customer_type_id=customer.customer_type_id,
        default_order_type_id=customer.default_order_type_id,
        parent_id=customer.parent_id,
        phone_number=customer.phone_number,
        notes=customer.notes,
        billing_address_line1=customer.billing_address_line1,
        billing_address_line2=customer.billing_address_line2,
        billing_city=customer.billing_city,
        billing_state=customer.billing_state,
        billing_postal_code=customer.billing_postal_code,
        billing_country=customer.billing_country,
        shipping_address_line1=customer.shipping_address_line1,
        shipping_address_line2=customer.shipping_address_line2,
        shipping_city=customer.shipping_city,
        shipping_state=customer.shipping_state,
        shipping_postal_code=customer.shipping_postal_code,
        shipping_country=customer.shipping_country,
    )
    values = _render_customer_form(
        default, type_choices, parent_choices, order_type_choices, key_prefix="edit"
    )
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="edit_save_btn"):
            if not values["customer_name"]:
                st.error("Customer name is required.")
            else:
                with session_scope() as session:
                    update_customer(session, customer_id, **values)
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="edit_cancel_btn"):
            st.rerun()


@st.dialog("Add customer", width="large")
def add_customer_dialog() -> None:
    with session_scope() as session:
        type_choices = [(t.customer_type_id, t.name) for t in list_customer_types(session)]
        order_type_choices = list_order_type_choices(session)
        parent_choices = list_customer_choices(session)

    values = _render_customer_form(
        {}, type_choices, parent_choices, order_type_choices, key_prefix="add"
    )
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", width="stretch", key="add_save_btn"):
            if not values["customer_name"]:
                st.error("Customer name is required.")
            else:
                with session_scope() as session:
                    new_customer = create_customer(session, **values)
                if new_customer.store_key is None:
                    st.session_state["store_key_range_exhausted"] = True
                st.query_params["customer_id"] = str(new_customer.customer_id)
                st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key="add_cancel_btn"):
            st.rerun()
