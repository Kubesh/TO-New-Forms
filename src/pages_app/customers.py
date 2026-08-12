import html

import streamlit as st

from src.db import session_scope
from src.services.customers import (
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
    border: 1px solid rgba(128, 128, 128, 0.35);
    border-radius: 0.5rem;
    padding: 1rem 1.25rem;
    width: 100%;
    box-sizing: border-box;
    transition: border-color 0.15s ease;
}
.customer-card-link:hover .customer-card {
    border-color: rgba(128, 128, 128, 0.7);
}
.customer-card-has-parent {
    border-color: #2563eb;
    border-width: 2px;
}
.customer-card-link:hover .customer-card-has-parent {
    border-color: #1d4ed8;
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
        if st.button("Add customer", use_container_width=True):
            add_customer_dialog()

    try:
        with session_scope() as session:
            type_choices = list_customer_types(session)
            state_choices = list_distinct_shipping_states(session)
            chain_choices = list_distinct_chain_names(session)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    col_type, col_state, col_chain = st.columns(3)
    with col_type:
        type_choice = st.selectbox("Account type", ["All types"] + [t.name for t in type_choices])
    with col_state:
        state_choice = st.selectbox("Shipping state", ["All states"] + state_choices)
    with col_chain:
        chain_choice = st.selectbox("Chain name", ["All chains"] + chain_choices)

    type_id = None
    if type_choice != "All types":
        type_id = next(t.customer_type_id for t in type_choices if t.name == type_choice)
    shipping_state = None if state_choice == "All states" else state_choice
    chain_name = None if chain_choice == "All chains" else chain_choice

    filters_key = (query, type_id, shipping_state, chain_name)
    if st.session_state.get("customer_filters_key") != filters_key:
        st.session_state["customer_filters_key"] = filters_key
        st.session_state["customer_page"] = 1
    page = st.session_state.get("customer_page", 1)

    try:
        with session_scope() as session:
            total = count_customers(session, query, type_id, shipping_state, chain_name)
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
                    limit=PAGE_SIZE,
                    offset=(page - 1) * PAGE_SIZE,
                )
                duplicate_names = get_duplicate_customer_names(session)
            else:
                customers = []
                duplicate_names = set()
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not customers:
        st.info("No customers found.")
        return

    cards_html = "".join(
        _card_html(customer, customer.customer_name in duplicate_names) for customer in customers
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
        if st.button("← Previous", disabled=page <= 1, use_container_width=True):
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
        if st.button("Next →", disabled=page >= total_pages, use_container_width=True):
            st.session_state["customer_page"] = page + 1
            st.rerun()


def _card_html(customer, is_duplicate: bool) -> str:
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

    if not customer:
        st.warning("Customer not found.")
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
        if st.button("Edit customer", use_container_width=True):
            edit_customer_dialog(customer.customer_id)

    st.header(customer.customer_name)
    st.caption(customer.customer_type.name if customer.customer_type else "No type")
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


def _render_customer_form(default: dict, type_choices, parent_choices, key_prefix: str) -> dict:
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
        parent_choices = list_customer_choices(session, exclude_customer_id=customer_id)

    if not customer:
        st.error("Customer not found.")
        return

    default = dict(
        customer_name=customer.customer_name,
        customer_type_id=customer.customer_type_id,
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
    values = _render_customer_form(default, type_choices, parent_choices, key_prefix="edit")
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", use_container_width=True, key="edit_save_btn"):
            if not values["customer_name"]:
                st.error("Customer name is required.")
            else:
                with session_scope() as session:
                    update_customer(session, customer_id, **values)
                st.rerun()
    with col_cancel:
        if st.button("Cancel", use_container_width=True, key="edit_cancel_btn"):
            st.rerun()


@st.dialog("Add customer", width="large")
def add_customer_dialog() -> None:
    with session_scope() as session:
        type_choices = [(t.customer_type_id, t.name) for t in list_customer_types(session)]
        parent_choices = list_customer_choices(session)

    values = _render_customer_form({}, type_choices, parent_choices, key_prefix="add")
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", use_container_width=True, key="add_save_btn"):
            if not values["customer_name"]:
                st.error("Customer name is required.")
            else:
                with session_scope() as session:
                    new_customer = create_customer(session, **values)
                st.query_params["customer_id"] = str(new_customer.customer_id)
                st.rerun()
    with col_cancel:
        if st.button("Cancel", use_container_width=True, key="add_cancel_btn"):
            st.rerun()
