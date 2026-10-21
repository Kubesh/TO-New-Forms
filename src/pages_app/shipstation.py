import os

import pandas as pd
import streamlit as st

from src.db import session_scope
from src.services.order_shipstation import check_all_labels, list_recent_sends
from src.services.app_settings import set_setting
from src.services.shipstation import (
    ShipStationError,
    ShipStationNotConfigured,
    check_connection,
    configured_shipping_method,
    list_carriers,
    list_services,
)


def _format(value) -> str:
    return value.strftime("%m/%d/%y %I:%M %p") if value else ""


def shipstation_page() -> None:
    st.title("ShipStation")
    st.caption(
        "POs are sent to ShipStation from their detail page. Labels created there are "
        "picked up by the label check on the PO (or the scheduled sync script)."
    )

    if st.button("Test connection", key="shipstation_test"):
        try:
            with st.spinner("Checking ShipStation…"):
                stores = check_connection()
            st.success(
                f"Connected to ShipStation ({len(stores)} store{'' if len(stores) == 1 else 's'} "
                "on the account)."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Store ID": store.get("storeId"),
                            "Name": store.get("storeName"),
                            "Marketplace": store.get("marketplaceName"),
                            "Active": "Yes" if store.get("active") else "No",
                        }
                        for store in stores
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Set SHIPSTATION_STORE_ID in .env to a Store ID above to file new orders "
                "under that store; leave it blank for ShipStation's default."
            )
        except (ShipStationNotConfigured, ShipStationError) as exc:
            st.error(str(exc))
    store_id = os.environ.get("SHIPSTATION_STORE_ID", "").strip()
    st.write(f"**Store:** {store_id or 'ShipStation default'}")

    _render_shipping_method()

    st.subheader("Recent sends")
    _render_check_labels()
    try:
        with session_scope() as session:
            sends = list_recent_sends(session, 50)
    except RuntimeError as exc:
        st.error(str(exc))
        return
    if not sends:
        st.write("Nothing has been sent to ShipStation yet.")
        return
    frame = pd.DataFrame(
        [
            {
                "PO": po_number,
                "Sent": _format(send.sent_at),
                "ShipStation order": send.order_number or send.shipstation_order_id,
                "Label created": _format(send.label_created_at),
                "Carrier": send.carrier_code or "",
                "Tracking": send.tracking_number or "",
            }
            for send, po_number in sends
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")


def _render_check_labels() -> None:
    if st.button("Check ShipStation", key="ss_check_all"):
        progress = st.progress(0.0, text="Checking ShipStation…")

        def on_progress(done: int, total: int) -> None:
            progress.progress(done / total, text=f"Checked {done} of {total} orders…")

        try:
            with session_scope() as session:
                result = check_all_labels(session, on_progress)
        except (ShipStationNotConfigured, ShipStationError) as exc:
            progress.empty()
            st.error(str(exc))
        else:
            progress.empty()
            if result["checked"] == 0:
                st.info("No orders are waiting on a label.")
            else:
                st.success(
                    f"Checked {result['checked']} order(s) without a label: "
                    f"{result['found']} now have one."
                )
    st.caption("Looks up label, tracking and carrier for every sent order that doesn't have a label yet.")


def _is_fedex(option: dict) -> bool:
    return "fedex" in f"{option['name']} {option['code']}".lower()


def _is_fedex_ground(option: dict) -> bool:
    name = option["name"].lower()
    return name == "fedex ground" or ("ground" in name and "home" not in name)


def _pick_default(options: list[dict], saved_code: str | None, preferred) -> int:
    """Index of the saved choice; failing that the first option `preferred`
    accepts (FedEx / FedEx Ground); failing that 0."""
    if saved_code:
        for index, option in enumerate(options):
            if option["code"] == saved_code:
                return index
        return 0
    return next((i for i, option in enumerate(options) if preferred(option)), 0)


def _render_shipping_method() -> None:
    st.subheader("Shipping method for new orders")
    st.caption(
        "Orders sent from a PO are created in ShipStation with this carrier and service. "
        "Whoever prints the label can still change it in ShipStation."
    )
    try:
        with session_scope() as session:
            current = configured_shipping_method(session)
    except RuntimeError as exc:
        st.error(str(exc))
        return
    if current:
        st.write(f"**Current:** {current['name']}")
    else:
        st.write("**Current:** not set - ShipStation uses its own default.")

    if st.button("Choose carrier and service…", key="ss_load_carriers"):
        try:
            with st.spinner("Loading carriers from ShipStation…"):
                st.session_state["ss_carriers"] = list_carriers()
            st.session_state["ss_services"] = {}
        except (ShipStationNotConfigured, ShipStationError) as exc:
            st.error(str(exc))
    carriers = st.session_state.get("ss_carriers")
    if carriers is None:
        return
    if not carriers:
        st.info("ShipStation reports no carriers on this account.")
        return

    carrier_index = _pick_default(carriers, current["carrier_code"] if current else None, _is_fedex)
    carrier = carriers[
        st.selectbox(
            "Carrier",
            range(len(carriers)),
            index=carrier_index,
            format_func=lambda i: carriers[i]["name"],
            key="ss_carrier_pick",
        )
    ]
    services_cache = st.session_state.setdefault("ss_services", {})
    if carrier["code"] not in services_cache:
        try:
            with st.spinner("Loading services…"):
                services_cache[carrier["code"]] = list_services(carrier["code"])
        except (ShipStationNotConfigured, ShipStationError) as exc:
            st.error(str(exc))
            return
    services = services_cache[carrier["code"]]
    if not services:
        st.info("No domestic services for that carrier.")
        return
    saved_service = current["service_code"] if current and current["carrier_code"] == carrier["code"] else None
    service = services[
        st.selectbox(
            "Service",
            range(len(services)),
            index=_pick_default(services, saved_service, _is_fedex_ground),
            format_func=lambda i: services[i]["name"],
            key=f"ss_service_pick_{carrier['code']}",
        )
    ]
    col_save, col_clear = st.columns(2)
    with col_save:
        if st.button("Save as the default", type="primary", width="stretch", key="ss_save_method"):
            with session_scope() as session:
                set_setting(session, "shipstation_carrier_code", carrier["code"])
                set_setting(session, "shipstation_service_code", service["code"])
                set_setting(session, "shipstation_service_name", service["name"])
            st.session_state.pop("ss_carriers", None)
            st.toast(f"New orders will use {service['name']}.")
            st.rerun()
    with col_clear:
        if st.button("Use ShipStation's default", width="stretch", key="ss_clear_method"):
            with session_scope() as session:
                for key in ("shipstation_carrier_code", "shipstation_service_code", "shipstation_service_name"):
                    set_setting(session, key, None)
            st.session_state.pop("ss_carriers", None)
            st.rerun()
