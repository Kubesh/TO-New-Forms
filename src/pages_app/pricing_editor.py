"""The pricing editor shared by the customer type and customer pages: a Line
tab (one price per line / sub sub category) and a SKU tab (one price per SKU,
which overrides the line / sub sub category price).

Each price is a card row with a small edit button. Edits are staged (the row
turns yellow) and only written when Save is pressed in the bar at the top;
Cancel throws them away."""
import html
from decimal import Decimal

import streamlit as st

from src.db import session_scope
from src.services.pricing import line_price_rows, set_prices, sku_price_rows

PENDING = "pricing_pending"
ACTIVE_SCOPE = "pricing_active_scope"

PRICING_CSS = """
<style>
[class*="st-key-pricerow-"] {
    border-bottom: 1px solid rgba(26, 23, 18, 0.18);
    padding: 0.3rem 0.5rem 0.5rem;
    gap: 0;
    margin-bottom: -0.55rem;
}
[class*="st-key-pricerow-"] [data-testid="stHorizontalBlock"] { gap: 0.5rem; }
[class*="st-key-pricerow-"] button {
    min-height: 1.9rem;
    height: 1.9rem;
    padding: 0 0.6rem;
}
[class*="st-key-pricerow-changed-"] { background: #FFF2A8; }
.price-row-name { font-weight: 700; line-height: 1.3; }
.price-row-sub { font-size: 0.78rem; opacity: 0.65; line-height: 1.25; }
.price-row-amount { font-size: 1rem; line-height: 1.3; font-weight: 700; text-align: right; }
.price-row-badge {
    display: block; text-align: right; font-size: 0.7rem; opacity: 0.65; line-height: 1.2;
    text-transform: uppercase; letter-spacing: 0.04em;
}
.st-key-pricing-savebar {
    position: sticky; top: 3.5rem; z-index: 50;
    background: #FFF2A8; border: 2px solid #1A1712; border-radius: 0.625rem;
    padding: 0.5rem 0.9rem; margin-bottom: 0.75rem;
}
</style>
"""


def _money(value) -> str:
    return "No price" if value is None else f"${Decimal(value):,.2f}"


def _pending() -> dict:
    return st.session_state.setdefault(PENDING, {})


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

    # Staged edits belong to one scope; arriving at a different one drops them.
    if st.session_state.get(ACTIVE_SCOPE) != key:
        st.session_state[ACTIVE_SCOPE] = key
        st.session_state[PENDING] = {}
    pending = _pending()

    st.markdown(PRICING_CSS, unsafe_allow_html=True)
    if pending:
        with st.container(key="pricing-savebar"):
            col_text, col_save, col_cancel = st.columns([3, 1, 1])
            with col_text:
                st.write(
                    f"**{len(pending)} unsaved price change{'s' if len(pending) != 1 else ''}**"
                )
            with col_save:
                if st.button("Save", type="primary", width="stretch", key=f"{key}_save"):
                    changes = [
                        {
                            ("category_id" if target.startswith("c:") else "item_id"): int(
                                target[2:]
                            ),
                            "price": price,
                            **scope,
                        }
                        for target, (price, _) in pending.items()
                    ]
                    with session_scope() as session:
                        set_prices(session, changes)
                    st.session_state[PENDING] = {}
                    st.toast(f"Saved {len(changes)} price change{'s' if len(changes) != 1 else ''}.")
                    st.rerun()
            with col_cancel:
                if st.button("Cancel", width="stretch", key=f"{key}_cancel"):
                    st.session_state[PENDING] = {}
                    st.rerun()

    st.caption(
        f"Per-case prices for {who}. The price shown is what a new purchase order line gets; "
        f"\"{own_label}\" marks one set here, the rest is inherited. Changes apply to purchase "
        "orders entered from now on - existing POs keep the price they were entered at."
    )
    tab_line, tab_sku = st.tabs(["Line", "SKU"])

    with tab_line:
        with session_scope() as session:
            rows = line_price_rows(session, **scope)
        if not rows:
            st.info(
                "No lines yet. Add them on the Categories page, under Sellable Product, "
                "as subcategories (lines) and sub sub categories."
            )
        else:
            st.caption(
                "One price for every item in a line / sub sub category. A SKU price on the SKU "
                "tab overrides it."
            )
        for row in rows:
            path = row["path"]
            line = path[1] if len(path) > 1 else path[0]
            sub = path[2] if len(path) > 2 else None
            title = f"{line} › {sub}" if sub else line
            _price_row(
                target=f"c:{row['category_id']}",
                title=title,
                subtitle="",
                own=row["own"],
                effective=row["effective"],
                own_label=own_label,
                key=key,
            )

    with tab_sku:
        with session_scope() as session:
            rows = sku_price_rows(session, **scope)
        if not rows:
            st.info("No sellable items yet.")
        else:
            st.caption(
                "A price on a single SKU. It overrides the line / sub sub category price for "
                "this item only."
            )
            search = st.text_input(
                "Search SKUs",
                placeholder="Search by SKU or name…",
                label_visibility="collapsed",
                key=f"{key}_sku_search",
            ).strip().lower()
            for row in rows:
                if search and search not in f"{row['sku']} {row['name']}".lower():
                    continue
                _price_row(
                    target=f"i:{row['item_id']}",
                    title=row["sku"],
                    subtitle=f"{row['name']}  ·  {row['category']}",
                    own=row["own"],
                    effective=row["effective"],
                    own_label=own_label,
                    key=key,
                )


def _price_row(
    *, target: str, title: str, subtitle: str, own, effective, own_label: str, key: str
) -> None:
    pending = _pending()
    changed = target in pending
    amount, badge = _money(effective), (own_label if own is not None else "")
    if changed:
        new_price, _ = pending[target]
        if new_price is not None:
            amount, badge = _money(new_price), f"{own_label} · unsaved"
        elif own is not None:
            # Removed here: the inherited price isn't known until it's saved.
            amount, badge = "Inherited", "Removing · unsaved"
        else:
            badge = "Unsaved"

    safe_target = target.replace(":", "-")
    with st.container(key=f"pricerow-{'changed-' if changed else ''}{safe_target}"):
        col_name, col_price, col_edit = st.columns([6, 3, 1], vertical_alignment="center")
        with col_name:
            st.markdown(
                f'<div class="price-row-name">{html.escape(title)}</div>'
                + (f'<div class="price-row-sub">{html.escape(subtitle)}</div>' if subtitle else ""),
                unsafe_allow_html=True,
            )
        with col_price:
            st.markdown(
                f'<div class="price-row-amount">{html.escape(amount)}</div>'
                f'<span class="price-row-badge">{html.escape(badge)}</span>',
                unsafe_allow_html=True,
            )
        with col_edit:
            if st.button("✎", key=f"{key}_edit_{safe_target}", help="Edit price"):
                edit_price_dialog(target, title, own, effective, own_label)


@st.dialog("Edit price")
def edit_price_dialog(target: str, title: str, own, effective, own_label: str) -> None:
    pending = _pending()
    if target in pending and pending[target][0] is not None:
        start = pending[target][0]
    else:
        start = own if own is not None else effective
    st.write(f"**{title}**")
    price = st.number_input(
        "Price per case",
        min_value=0.0,
        step=0.01,
        format="%.2f",
        value=float(start) if start is not None else 0.0,
        key=f"edit_price_{target}",
    )

    col_set, col_remove, col_cancel = st.columns(3)
    with col_set:
        if st.button("Set price", type="primary", width="stretch", key=f"edit_price_set_{target}"):
            _stage(target, Decimal(str(price)), own)
            st.rerun()
    with col_remove:
        if st.button(
            "Remove",
            width="stretch",
            disabled=own is None and target not in pending,
            help=f"Remove the {own_label.lower()} set here, so it's inherited again.",
            key=f"edit_price_remove_{target}",
        ):
            _stage(target, None, own)
            st.rerun()
    with col_cancel:
        if st.button("Cancel", width="stretch", key=f"edit_price_cancel_{target}"):
            st.rerun()


def _stage(target: str, price: Decimal | None, own) -> None:
    """Stages a change - or drops it if it just restores what's saved."""
    pending = _pending()
    same = (price is None and own is None) or (
        price is not None and own is not None and Decimal(own) == price
    )
    if same:
        pending.pop(target, None)
    else:
        pending[target] = (price, own)
