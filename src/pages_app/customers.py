import streamlit as st

from src.db import session_scope
from src.services.customers import get_customer, search_customers

ADDRESS_FIELDS = (
    "address_line1",
    "address_line2",
    "city",
    "state",
    "postal_code",
    "country",
)


def customers_page() -> None:
    st.title("Customers")

    if st.session_state.get("selected_customer_id"):
        _render_detail(st.session_state["selected_customer_id"])
        return

    query = st.text_input(
        "Search customers",
        placeholder="Search by name…",
        label_visibility="collapsed",
    )

    try:
        with session_scope() as session:
            customers = search_customers(session, query)
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not customers:
        st.info("No customers found.")
        return

    cols_per_row = 3
    for i in range(0, len(customers), cols_per_row):
        row = customers[i : i + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, customer in zip(cols, row):
            with col:
                _render_card(customer)


def _render_card(customer) -> None:
    with st.container(border=True):
        st.subheader(customer.customer_name)
        st.caption(customer.customer_type.name if customer.customer_type else "No type")

        city = customer.billing_city or customer.shipping_city
        state = customer.billing_state or customer.shipping_state
        location = ", ".join(filter(None, [city, state]))
        if location:
            st.write(location)

        if st.button("View", key=f"view_customer_{customer.customer_id}"):
            st.session_state["selected_customer_id"] = customer.customer_id
            st.rerun()


def _render_detail(customer_id: int) -> None:
    with session_scope() as session:
        customer = get_customer(session, customer_id)

    if not customer:
        st.warning("Customer not found.")
        if st.button("← Back to list"):
            st.session_state.pop("selected_customer_id", None)
            st.rerun()
        return

    if st.button("← Back to list"):
        st.session_state.pop("selected_customer_id", None)
        st.rerun()

    st.header(customer.customer_name)
    st.caption(customer.customer_type.name if customer.customer_type else "No type")
    if customer.parent:
        st.write(f"Parent account: **{customer.parent.customer_name}**")

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
