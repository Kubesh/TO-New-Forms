import html

import streamlit as st

from src.db import session_scope
from src.models import Customer, Item
from src.services import qbo_sync
from src.services import quickbooks as qb
from src.services.categories import category_path
from src.services.customers import get_customer

QBO_ERRORS = (qb.QuickBooksNotConfigured, qb.QuickBooksNotConnected, qb.QuickBooksError)


def _show_error(exc: Exception) -> None:
    st.error(str(exc))


HEADER_COLUMNS = [4, 4, 2]


def _render_headers() -> None:
    col_app, col_qbo, _ = st.columns(HEADER_COLUMNS)
    with col_app:
        st.markdown("**Operations App**")
    with col_qbo:
        st.markdown("**QuickBooks**")


def _two_line(title: str, sub: str | None) -> str:
    small = f'<div style="font-size:0.8rem; opacity:0.65;">{html.escape(sub)}</div>' if sub else ""
    return f'<div>{html.escape(title)}</div>{small}'


SUPPORT_EMAIL = "adrian@rznce.com"


def quickbooks_page() -> None:
    st.title("QuickBooks")
    st.caption(f"Questions or problems with the QuickBooks connection? Contact {SUPPORT_EMAIL}.")
    tab_status, tab_customers, tab_items = st.tabs(["Connection", "Customers", "Items"])
    with tab_status:
        _render_status()
    with tab_customers:
        _render_customers()
    with tab_items:
        _render_items()


# --- connection -------------------------------------------------------------


def _render_status() -> None:
    try:
        with session_scope() as session:
            environment = qb.environment()
            connection = qb.get_connection(session)
            if connection is None:
                st.warning(
                    "QuickBooks isn't connected yet. Run `python scripts/qbo_connect.py` "
                    "on the server and approve the connection."
                )
                return
            realm = connection.realm_id
            company = qb.company_info(session)
            customers = qbo_sync.billing_customers(session)
            linked = qbo_sync.customer_links_by_id(session)
            items = qbo_sync.sellable_items(session)
            item_links = qbo_sync.current_item_links(session)
    except QBO_ERRORS as exc:
        _show_error(exc)
        return
    st.write(f"**Company:** {company.get('CompanyName', '(unknown)')}")
    st.write(f"**Environment:** {environment}  ·  **Company ID:** {realm}")
    if environment == "sandbox":
        st.info("This is the QuickBooks sandbox (test data) - nothing here touches the real books.")
    st.write(
        f"**Customers linked:** {sum(1 for c in customers if c.customer_id in linked)} of "
        f"{len(customers)} (stores of a parent account use the parent's link unless linked on their own)"
    )
    st.write(
        f"**Sellable SKUs linked:** {sum(1 for i in items if i.item_id in item_links)} of {len(items)}"
    )



# --- shared dialogs ---------------------------------------------------------


@st.dialog("Link to a QuickBooks customer")
def link_customer_dialog(customer_id: int) -> None:
    with session_scope() as session:
        customer = get_customer(session, customer_id)
        link = qbo_sync.get_customer_link(session, customer_id)
    if customer is None:
        st.error("Customer not found.")
        return
    st.write(f"**{customer.customer_name}**")
    if link:
        st.caption(f"Currently linked to: {link.qbo_display_name or link.qbo_customer_id}")

    key = f"qbo_cust_{customer_id}"
    text = st.text_input(
        "Search QuickBooks customers", value=customer.customer_name, key=f"{key}_text"
    )
    if st.button("Search", key=f"{key}_search"):
        try:
            with session_scope() as session:
                st.session_state[f"{key}_results"] = qbo_sync.search_qbo_customers(session, text)
        except QBO_ERRORS as exc:
            _show_error(exc)
    results = st.session_state.get(f"{key}_results")
    if results is not None:
        if not results:
            st.caption("No matching QuickBooks customers.")
        else:
            labels = {f"{r.get('DisplayName')}  (#{r['Id']})": r for r in results}
            choice = st.radio("Matches", list(labels), key=f"{key}_choice")
            if st.button("Link this customer", type="primary", key=f"{key}_link"):
                picked = labels[choice]
                try:
                    with session_scope() as session:
                        qbo_sync.link_customer(
                            session, customer_id, str(picked["Id"]), picked.get("DisplayName")
                        )
                except (ValueError, *QBO_ERRORS) as exc:
                    _show_error(exc)
                else:
                    st.session_state.pop(f"{key}_results", None)
                    st.rerun()

    st.divider()
    st.caption("Not in QuickBooks yet?")
    if st.button(
        f"Create \"{customer.customer_name}\" in QuickBooks", key=f"{key}_create"
    ):
        try:
            with session_scope() as session:
                qbo_sync.create_qbo_customer(session, get_customer(session, customer_id))
        except QBO_ERRORS as exc:
            _show_error(exc)
        else:
            st.session_state.pop(f"{key}_results", None)
            st.rerun()
    if link and st.button("Remove the link", key=f"{key}_unlink"):
        with session_scope() as session:
            qbo_sync.unlink_customer(session, customer_id)
        st.rerun()


@st.dialog("Link to a QuickBooks item")
def link_item_dialog(item_id: int) -> None:
    with session_scope() as session:
        item = session.get(Item, item_id)
        link = qbo_sync.current_item_links(session).get(item_id)
    if item is None:
        st.error("Item not found.")
        return
    st.write(f"**{item.sku}** - {item.name}")
    if link:
        st.caption(f"Currently linked to: {link.qbo_item_name or link.qbo_item_id}")

    key = f"qbo_item_{item_id}"
    text = st.text_input("Search QuickBooks items", value=item.name, key=f"{key}_text")
    if st.button("Search", key=f"{key}_search"):
        try:
            with session_scope() as session:
                st.session_state[f"{key}_results"] = qbo_sync.search_qbo_items(session, text)
        except QBO_ERRORS as exc:
            _show_error(exc)
    results = st.session_state.get(f"{key}_results")
    if results is not None:
        if not results:
            st.caption("No matching QuickBooks items.")
        else:
            labels = {
                f"{r.get('Name')}{'  ·  ' + r['Sku'] if r.get('Sku') else ''}  (#{r['Id']})": r
                for r in results
            }
            choice = st.radio("Matches", list(labels), key=f"{key}_choice")
            if st.button("Link this item", type="primary", key=f"{key}_link"):
                picked = labels[choice]
                try:
                    with session_scope() as session:
                        qbo_sync.link_item(session, item_id, str(picked["Id"]), picked.get("Name"))
                except (ValueError, *QBO_ERRORS) as exc:
                    _show_error(exc)
                else:
                    st.session_state.pop(f"{key}_results", None)
                    st.rerun()
    if link and st.button("Remove the link", key=f"{key}_unlink"):
        with session_scope() as session:
            qbo_sync.unlink_item(session, item_id)
        st.rerun()


# --- customers --------------------------------------------------------------


def _render_customers() -> None:
    try:
        with session_scope() as session:
            connected = qb.get_connection(session) is not None
    except QBO_ERRORS as exc:
        _show_error(exc)
        return
    if not connected:
        st.info("Connect QuickBooks first (see the Connection tab).")
        return

    st.caption(
        "Link each customer that gets invoiced to its QuickBooks customer. Stores that "
        "belong to a parent account are invoiced through the parent, so only the parent "
        "needs a link."
    )
    if st.button("Find exact name matches", key="qbo_match_customers"):
        try:
            with session_scope() as session:
                matches, left = qbo_sync.plan_customer_matches(session)
                st.session_state["qbo_customer_matches"] = (
                    [(c.customer_id, c.customer_name, str(q["Id"]), q.get("DisplayName")) for c, q in matches],
                    left,
                )
        except QBO_ERRORS as exc:
            _show_error(exc)
    plan = st.session_state.get("qbo_customer_matches")
    if plan is not None:
        matches, left = plan
        if matches:
            st.write(
                f"**{len(matches)}** customer{'' if len(matches) == 1 else 's'} match a "
                "QuickBooks customer by name exactly:"
            )
            for _, name, qbo_id, qbo_name in matches:
                st.caption(f"{name}  →  {qbo_name} (#{qbo_id})")
            if st.button(f"Link these {len(matches)}", type="primary", key="qbo_apply_customer_matches"):
                try:
                    with session_scope() as session:
                        for customer_id, _, qbo_id, qbo_name in matches:
                            qbo_sync.link_customer(session, customer_id, qbo_id, qbo_name)
                except (ValueError, *QBO_ERRORS) as exc:
                    _show_error(exc)
                else:
                    st.session_state.pop("qbo_customer_matches", None)
                    st.rerun()
        else:
            st.caption("No more exact name matches.")
        st.caption(f"{left} customer{'' if left == 1 else 's'} would still need linking by hand.")

    _render_customer_sync()

    with session_scope() as session:
        customers = qbo_sync.billing_customers(session)
        links = qbo_sync.customer_links_by_id(session)
    search = st.text_input(
        "Filter customers", placeholder="Filter by name…", label_visibility="collapsed", key="qbo_cust_filter"
    ).strip().lower()
    show = st.radio("Show", ["Not linked", "Linked", "All"], horizontal=True, key="qbo_cust_show")
    shown = [
        c
        for c in customers
        if (not search or search in c.customer_name.lower())
        and (show == "All" or (show == "Linked") == (c.customer_id in links))
    ]
    st.caption(f"{len(shown)} customer{'' if len(shown) == 1 else 's'}")
    _render_headers()
    for customer in shown[:200]:
        link = links.get(customer.customer_id)
        col_name, col_status, col_btn = st.columns(HEADER_COLUMNS, vertical_alignment="center")
        with col_name:
            st.markdown(_two_line(customer.customer_name, None), unsafe_allow_html=True)
        with col_status:
            if link:
                st.markdown(
                    _two_line(link.qbo_display_name or link.qbo_customer_id, f"#{link.qbo_customer_id}"),
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Not linked")
        with col_btn:
            if st.button(
                "Change" if link else "Link…", width="stretch", key=f"qbo_cust_btn_{customer.customer_id}"
            ):
                link_customer_dialog(customer.customer_id)
    if len(shown) > 200:
        st.caption("Showing the first 200 - use the filter to narrow the list.")


SYNC_FIELD_LABELS = {
    "bill_to_email": "Bill-to email",
    "phone_number": "Phone",
    "billing": "Billing address",
    "shipping": "Shipping address",
}


def _sync_field_group(field_name: str) -> str:
    return field_name.split("_", 1)[0] if field_name.startswith(("billing_", "shipping_")) else field_name


def _render_customer_sync() -> None:
    st.divider()
    st.markdown("**Sync customer details**")
    st.caption(
        "Fills in blanks on linked customers from QuickBooks: bill-to email, phone, and "
        "billing/shipping address. Anything already filled in here is left alone, and an "
        "address is only copied when that whole address is empty."
    )
    if st.button("Check for details to fill in", key="qbo_sync_customers_check"):
        try:
            with session_scope() as session:
                st.session_state["qbo_customer_sync"] = qbo_sync.plan_customer_sync(session)
        except QBO_ERRORS as exc:
            _show_error(exc)
    plan = st.session_state.get("qbo_customer_sync")
    if plan is None:
        return
    if not plan:
        st.caption("Nothing to fill in - every linked customer already has what QuickBooks has.")
        return

    counts: dict[str, int] = {}
    for entry in plan:
        for group in {_sync_field_group(f) for f in entry["fields"]}:
            counts[group] = counts.get(group, 0) + 1
    st.write(
        f"**{len(plan)}** customer{'' if len(plan) == 1 else 's'} would be updated: "
        + ", ".join(f"{SYNC_FIELD_LABELS[group]} ({n})" for group, n in counts.items())
    )
    with st.expander("See the changes"):
        for entry in plan[:200]:
            groups = []
            for group in dict.fromkeys(_sync_field_group(f) for f in entry["fields"]):
                values = [v for f, v in entry["fields"].items() if _sync_field_group(f) == group]
                groups.append(f"{SYNC_FIELD_LABELS[group]}: {', '.join(values)}")
            st.caption(f"**{entry['name']}** ← {entry['qbo_name']}  —  " + "  |  ".join(groups))
        if len(plan) > 200:
            st.caption(f"…and {len(plan) - 200} more.")
    if st.button(f"Fill in {len(plan)} customer{'' if len(plan) == 1 else 's'}", type="primary", key="qbo_sync_customers_apply"):
        with session_scope() as session:
            changed = qbo_sync.apply_customer_sync(session, plan)
        st.session_state.pop("qbo_customer_sync", None)
        st.toast(f"Updated {changed} customer{'' if changed == 1 else 's'} from QuickBooks.")
        st.rerun()


# --- items ------------------------------------------------------------------


def _render_items() -> None:
    try:
        with session_scope() as session:
            connected = qb.get_connection(session) is not None
    except QBO_ERRORS as exc:
        _show_error(exc)
        return
    if not connected:
        st.info("Connect QuickBooks first (see the Connection tab).")
        return

    st.caption(
        "Link each sellable SKU to its QuickBooks product/service. Prices come from this "
        "app's pricing, not from QuickBooks."
    )
    if st.button("Find matches by SKU or name", key="qbo_match_items"):
        try:
            with session_scope() as session:
                matches, left = qbo_sync.plan_item_matches(session)
                st.session_state["qbo_item_matches"] = (
                    [(i.item_id, i.sku, str(q["Id"]), q.get("Name")) for i, q in matches],
                    left,
                )
        except QBO_ERRORS as exc:
            _show_error(exc)
    plan = st.session_state.get("qbo_item_matches")
    if plan is not None:
        matches, left = plan
        if matches:
            st.write(
                f"**{len(matches)}** SKUs match a QuickBooks item (by its SKU field, else exact name):"
            )
            for _, sku, qbo_id, qbo_name in matches:
                st.caption(f"{sku}  →  {qbo_name} (#{qbo_id})")
            if st.button(f"Link these {len(matches)}", type="primary", key="qbo_apply_item_matches"):
                try:
                    with session_scope() as session:
                        for item_id, _, qbo_id, qbo_name in matches:
                            qbo_sync.link_item(session, item_id, qbo_id, qbo_name)
                except (ValueError, *QBO_ERRORS) as exc:
                    _show_error(exc)
                else:
                    st.session_state.pop("qbo_item_matches", None)
                    st.rerun()
        else:
            st.caption("No more matches.")
        st.caption(f"{left} SKU{'' if left == 1 else 's'} would still need linking by hand.")

    with session_scope() as session:
        items = []
        for item in qbo_sync.sellable_items(session):
            below_top = " › ".join(c.name for c in category_path(item.category)[1:])
            items.append(
                {
                    "item_id": item.item_id,
                    "sku": item.sku,
                    "title": f"{below_top}: {item.name}" if below_top else item.name,
                }
            )
        links = qbo_sync.current_item_links(session)
    search = st.text_input(
        "Filter SKUs", placeholder="Filter by SKU or name…", label_visibility="collapsed", key="qbo_item_filter"
    ).strip().lower()
    show = st.radio("Show", ["Not linked", "Linked", "All"], horizontal=True, key="qbo_item_show")
    shown = [
        i
        for i in items
        if (not search or search in f"{i['sku']} {i['title']}".lower())
        and (show == "All" or (show == "Linked") == (i["item_id"] in links))
    ]
    st.caption(f"{len(shown)} SKU{'' if len(shown) == 1 else 's'}")
    _render_headers()
    for item in shown[:200]:
        link = links.get(item["item_id"])
        col_name, col_status, col_btn = st.columns(HEADER_COLUMNS, vertical_alignment="center")
        with col_name:
            st.markdown(_two_line(item["title"], item["sku"]), unsafe_allow_html=True)
        with col_status:
            if link:
                st.markdown(
                    _two_line(link.qbo_item_name or link.qbo_item_id, f"#{link.qbo_item_id}"),
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Not linked")
        with col_btn:
            if st.button(
                "Change" if link else "Link…", width="stretch", key=f"qbo_item_btn_{item['item_id']}"
            ):
                link_item_dialog(item["item_id"])
    if len(shown) > 200:
        st.caption("Showing the first 200 - use the filter to narrow the list.")
