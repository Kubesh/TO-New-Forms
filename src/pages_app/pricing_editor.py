"""The pricing editor shared by the customer type and customer pages: a Line
tab (one price per line / form factor) and a SKU tab (one price per SKU, which
overrides the line / form factor price)."""
from decimal import Decimal

import pandas as pd
import streamlit as st

from src.db import session_scope
from src.services.pricing import line_price_rows, set_prices, sku_price_rows

PRICE_FORMAT = "$%.2f"


def _blank(value) -> bool:
    return value is None or pd.isna(value)


def _same(old, new) -> bool:
    if _blank(old) and _blank(new):
        return True
    if _blank(old) or _blank(new):
        return False
    return round(float(old), 4) == round(float(new), 4)


def _money(value) -> float | None:
    return None if value is None else float(value)


def render_pricing(
    *, customer_type_id: int | None = None, customer_id: int | None = None, key: str
) -> None:
    """key must be unique per scope on the page (it namespaces widget state)."""
    if customer_id is not None:
        own_label, who = "Customer price", "this customer"
    elif customer_type_id is not None:
        own_label, who = "Type price", "this customer type"
    else:
        own_label, who = "Default price", "customers with no price of their own"
    scope = {"customer_type_id": customer_type_id, "customer_id": customer_id}

    st.caption(
        f"Per-case prices for {who}. Leave a cell empty for no price of its own here. "
        "Changes apply to purchase orders entered from now on - existing POs keep the "
        "price they were entered at."
    )
    tab_line, tab_sku = st.tabs(["Line", "SKU"])

    with tab_line:
        with session_scope() as session:
            rows = line_price_rows(session, **scope)
        if not rows:
            st.info(
                "No lines yet. Add them on the Categories page, as subcategories "
                "(lines) and form factors."
            )
        else:
            st.caption(
                "One price for every item in a line / form factor. A SKU price on the SKU "
                "tab overrides it."
            )
            show_category = len({r["path"][0] for r in rows}) > 1
            data = []
            for r in rows:
                path = r["path"]
                row = {}
                if show_category:
                    row["Category"] = path[0]
                row["Line"] = path[1] if len(path) > 1 else path[0]
                row["Form factor"] = path[2] if len(path) > 2 else ""
                row["Items"] = r["items"]
                row[own_label] = _money(r["own"])
                row["Currently charged"] = _money(r["effective"])
                row["From"] = r["source"]
                data.append(row)
            _editor(
                pd.DataFrame(data),
                own_label,
                [{"category_id": r["category_id"], **scope} for r in rows],
                key=f"{key}_line",
            )

    with tab_sku:
        with session_scope() as session:
            rows = sku_price_rows(session, **scope)
        if not rows:
            st.info("No sellable items yet.")
        else:
            st.caption(
                "A price on a single SKU. It overrides the line / form factor price for this "
                "item only."
            )
            data = [
                {
                    "SKU": r["sku"],
                    "Item": r["name"],
                    "Line / form factor": r["category"],
                    own_label: _money(r["own"]),
                    "Currently charged": _money(r["effective"]),
                    "From": r["source"],
                }
                for r in rows
            ]
            _editor(
                pd.DataFrame(data),
                own_label,
                [{"item_id": r["item_id"], **scope} for r in rows],
                key=f"{key}_sku",
            )


def _editor(frame: pd.DataFrame, own_label: str, targets: list[dict], *, key: str) -> None:
    version = st.session_state.get(f"{key}_version", 0)
    edited = st.data_editor(
        frame,
        hide_index=True,
        width="stretch",
        disabled=[c for c in frame.columns if c != own_label],
        column_config={
            own_label: st.column_config.NumberColumn(
                own_label, min_value=0.0, step=0.01, format=PRICE_FORMAT
            ),
            "Currently charged": st.column_config.NumberColumn(
                "Currently charged", format=PRICE_FORMAT
            ),
            "From": st.column_config.TextColumn("From", width="large"),
        },
        key=f"{key}_editor_{version}",
    )

    changes = []
    for index, target in enumerate(targets):
        old, new = frame.iloc[index][own_label], edited.iloc[index][own_label]
        if not _same(old, new):
            changes.append({**target, "price": None if _blank(new) else Decimal(str(new))})

    if st.button("Save prices", type="primary", disabled=not changes, key=f"{key}_save"):
        with session_scope() as session:
            set_prices(session, changes)
        # A fresh editor key, so the saved edits aren't re-applied on top of the new data.
        st.session_state[f"{key}_version"] = version + 1
        st.toast(f"Saved {len(changes)} price change{'s' if len(changes) != 1 else ''}.")
        st.rerun()
    if changes:
        st.caption(f"{len(changes)} unsaved change{'s' if len(changes) != 1 else ''}.")
