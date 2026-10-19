import os

import pandas as pd
import streamlit as st

from src.db import session_scope
from src.services.order_shipstation import list_recent_sends
from src.services.shipstation import ShipStationError, ShipStationNotConfigured, check_connection


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
        except (ShipStationNotConfigured, ShipStationError) as exc:
            st.error(str(exc))
    store_id = os.environ.get("SHIPSTATION_STORE_ID", "").strip()
    st.write(f"**Store:** {store_id or 'ShipStation default'}")

    st.subheader("Recent sends")
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
                "Tracking": send.tracking_number or "",
            }
            for send, po_number in sends
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")
