from decimal import Decimal

import pandas as pd
import streamlit as st

from src.db import session_scope
from src.services.pricing import price_grid, set_prices

PRICE_FORMAT = "$%.2f"


def _is_blank(value) -> bool:
    return value is None or pd.isna(value)


def _same(old, new) -> bool:
    if _is_blank(old) and _is_blank(new):
        return True
    if _is_blank(old) or _is_blank(new):
        return False
    return round(float(old), 4) == round(float(new), 4)


def _to_price(value) -> Decimal | None:
    return None if _is_blank(value) else Decimal(str(value))


def pricing_page() -> None:
    st.title("Pricing")
    st.caption(
        "Per-case prices. A customer is charged, in order: their own price, their parent "
        "account's price, the price for their customer type, then the default. Leave a cell "
        "empty for no price. Changes apply to purchase orders entered from now on - existing "
        "POs keep the price they were entered at. Individual customer prices are set on the "
        "customer's page."
    )

    try:
        with session_scope() as session:
            items, types, prices = price_grid(session)
    except RuntimeError as exc:
        st.error(str(exc))
        return
    if not items:
        st.info("No sellable items yet.")
        return

    scopes = [("Default", None)] + [(t.name, t.customer_type_id) for t in types]
    frame = pd.DataFrame(
        [
            {
                "SKU": item.sku,
                "Item": item.name,
                **{
                    label: (float(prices[(item.item_id, type_id)]) if (item.item_id, type_id) in prices else None)
                    for label, type_id in scopes
                },
            }
            for item in items
        ]
    )

    version = st.session_state.get("pricing_grid_version", 0)
    edited = st.data_editor(
        frame,
        hide_index=True,
        width="stretch",
        disabled=["SKU", "Item"],
        column_config={
            label: st.column_config.NumberColumn(label, min_value=0.0, step=0.01, format=PRICE_FORMAT)
            for label, _ in scopes
        },
        key=f"pricing_grid_{version}",
    )

    changes = []
    for row_number, item in enumerate(items):
        for label, type_id in scopes:
            old, new = frame.iloc[row_number][label], edited.iloc[row_number][label]
            if not _same(old, new):
                changes.append(
                    {"item_id": item.item_id, "price": _to_price(new), "customer_type_id": type_id}
                )

    if st.button("Save prices", type="primary", disabled=not changes, key="save_prices_btn"):
        with session_scope() as session:
            set_prices(session, changes)
        # A fresh editor key, so the saved edits aren't re-applied on top of the new data.
        st.session_state["pricing_grid_version"] = version + 1
        st.toast(f"Saved {len(changes)} price change{'s' if len(changes) != 1 else ''}.")
        st.rerun()
    if changes:
        st.caption(f"{len(changes)} unsaved change{'s' if len(changes) != 1 else ''}.")
