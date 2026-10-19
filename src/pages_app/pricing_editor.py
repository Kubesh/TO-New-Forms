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
from src.services.pricing import (
    line_price_rows,
    set_exclusions,
    set_prices,
    sku_price_rows,
)

PENDING = "pricing_pending"
PENDING_EXCL = "pricing_pending_excl"  # category_id -> True if not sold
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
[class*="st-key-pricerow-"][class*="notsold-"] .price-row-name,
[class*="st-key-pricerow-"][class*="notsold-"] .price-row-amount { opacity: 0.45; }
[class*="st-key-pricerow-"][class*="notsold-"] .price-row-amount {
    font-weight: 400; font-style: italic;
}
.price-row-name { font-weight: 700; line-height: 1.3; }
.price-row-sub { font-size: 0.78rem; opacity: 0.65; line-height: 1.25; }
.price-row-amount { font-size: 1rem; line-height: 1.3; font-weight: 700; text-align: right; }
[data-testid="stDialog"] [data-testid="stNumberInputStepUp"],
[data-testid="stDialog"] [data-testid="stNumberInputStepDown"] { display: none; }
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


def _pending_excl() -> dict:
    return st.session_state.setdefault(PENDING_EXCL, {})


def render_pricing(
    *, customer_type_id: int | None = None, customer_id: int | None = None, key: str
) -> None:
    """key must be unique per scope on the page (it namespaces widget state)."""
    if customer_id is not None:
        own_label = "Customer price"
    elif customer_type_id is not None:
        own_label = "Type price"
    else:
        own_label = "Default price"
    scope = {"customer_type_id": customer_type_id, "customer_id": customer_id}

    # Staged edits belong to one scope; arriving at a different one drops them.
    if st.session_state.get(ACTIVE_SCOPE) != key:
        st.session_state[ACTIVE_SCOPE] = key
        st.session_state[PENDING] = {}
        st.session_state[PENDING_EXCL] = {}
    pending = _pending()
    pending_excl = _pending_excl()
    can_exclude = customer_id is not None or customer_type_id is not None
    who_short = "customer" if customer_id is not None else "customer type"

    st.markdown(PRICING_CSS, unsafe_allow_html=True)
    changes_count = len(pending) + len(pending_excl)
    if changes_count:
        with st.container(key="pricing-savebar"):
            col_text, col_save, col_cancel = st.columns([3, 1, 1])
            with col_text:
                st.write(
                    f"**{changes_count} unsaved change{'s' if changes_count != 1 else ''}**"
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
                    exclusions = [
                        {"category_id": category_id, "excluded": excluded, **scope}
                        for category_id, excluded in pending_excl.items()
                    ]
                    with session_scope() as session:
                        if changes:
                            set_prices(session, changes)
                        if exclusions:
                            set_exclusions(session, exclusions)
                    st.session_state[PENDING] = {}
                    st.session_state[PENDING_EXCL] = {}
                    st.toast(f"Saved {changes_count} change{'s' if changes_count != 1 else ''}.")
                    st.rerun()
            with col_cancel:
                if st.button("Cancel", width="stretch", key=f"{key}_cancel"):
                    st.session_state[PENDING] = {}
                    st.session_state[PENDING_EXCL] = {}
                    st.rerun()

    if customer_id is not None:
        intro = (
            "Per-case prices for this customer. These are used on their POs instead of "
            "their customer type's pricing."
        )
    elif customer_type_id is not None:
        intro = (
            "Per-case prices for this customer type. A customer's pricing on a PO will be "
            "set to this unless the customer has custom pricing set."
        )
    else:
        intro = "Per-case prices for customers with no pricing of their own."
    st.caption(f"{intro} You can set the pricing by the line or by the individual SKU.")
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
                exclusion=(
                    (row["category_id"], row["excluded_own"], row["excluded_inherited"], who_short)
                    if can_exclude
                    else None
                ),
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
                    title=f"{row['category']}: {row['name']}" if row["category"] else row["name"],
                    subtitle=row["sku"],
                    own=row["own"],
                    effective=row["effective"],
                    own_label=own_label,
                    key=key,
                    not_sold=row["excluded"],
                )


def _price_row(
    *,
    target: str,
    title: str,
    subtitle: str,
    own,
    effective,
    own_label: str,
    key: str,
    exclusion: tuple | None = None,
    not_sold: bool = False,
) -> None:
    """exclusion is (category_id, excluded here, excluded by a higher level,
    who) on a Line row that can be switched off; not_sold marks a SKU row whose
    category is switched off (read-only here)."""
    pending = _pending()
    changed = target in pending
    amount = _money(effective)
    if exclusion:
        category_id, excluded_own, excluded_inherited, _ = exclusion
        excluded_now = _pending_excl().get(category_id, excluded_own) or excluded_inherited
        changed = changed or category_id in _pending_excl()
        not_sold = excluded_now
    if not_sold:
        amount = "Not sold"
    elif changed and target in pending:
        new_price, _ = pending[target]
        if new_price is not None:
            amount = _money(new_price)
        elif own is not None:
            # Removed here: the inherited price isn't known until it's saved.
            amount = "Inherited"

    safe_target = target.replace(":", "-")
    row_key = f"pricerow-{'changed-' if changed else ''}{'notsold-' if not_sold else ''}{safe_target}"
    with st.container(key=row_key):
        col_name, col_price, col_edit = st.columns([6, 3, 1], vertical_alignment="center")
        with col_name:
            st.markdown(
                f'<div class="price-row-name">{html.escape(title)}</div>'
                + (f'<div class="price-row-sub">{html.escape(subtitle)}</div>' if subtitle else ""),
                unsafe_allow_html=True,
            )
        with col_price:
            st.markdown(
                f'<div class="price-row-amount">{html.escape(amount)}</div>',
                unsafe_allow_html=True,
            )
        with col_edit:
            # SKU rows of a switched-off category can't be priced or sold.
            if st.button(
                "✎",
                key=f"{key}_edit_{safe_target}",
                help="Edit price",
                disabled=not_sold and not exclusion,
            ):
                # A fresh nonce per opening, so widgets inside the dialog start from the
                # saved/staged values instead of whatever was left typed last time.
                st.session_state["edit_price_nonce"] = st.session_state.get("edit_price_nonce", 0) + 1
                edit_price_dialog(
                    target, title, own, effective, own_label, exclusion,
                    st.session_state["edit_price_nonce"],
                )


@st.dialog("Edit price")
def edit_price_dialog(
    target: str,
    title: str,
    own,
    effective,
    own_label: str,
    exclusion: tuple | None = None,
    nonce: int = 0,
) -> None:
    pending = _pending()
    if target in pending and pending[target][0] is not None:
        start = pending[target][0]
    else:
        start = own if own is not None else effective
    start = float(start) if start is not None else 0.0
    st.write(f"**{title}**")

    sold = True
    if exclusion:
        category_id, excluded_own, excluded_inherited, who = exclusion
        if excluded_inherited:
            st.checkbox(f"Sold to this {who}", value=False, disabled=True, key=f"edit_sold_{target}_{nonce}")
            st.caption("Switched off for a higher level (their parent account or customer type).")
            sold = False
        else:
            currently_excluded = _pending_excl().get(category_id, excluded_own)
            sold = st.checkbox(
                f"Sold to this {who}", value=not currently_excluded, key=f"edit_sold_{target}_{nonce}"
            )

    price = st.number_input(
        "Price per case",
        min_value=0.0,
        step=0.01,
        format="%.2f",
        value=start,
        disabled=not sold,
        key=f"edit_price_{target}_{nonce}",
    )

    col_set, col_remove, col_cancel = st.columns(3)
    with col_set:
        if st.button("Apply", type="primary", width="stretch", key=f"edit_price_set_{target}"):
            if exclusion and not exclusion[2]:
                _stage_exclusion(exclusion[0], not sold, exclusion[1])
            if sold and round(price, 4) != round(start, 4):
                _stage(target, Decimal(str(price)), own)
            st.rerun()
    with col_remove:
        if st.button(
            "Remove price",
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


def _stage_exclusion(category_id: int, excluded: bool, saved: bool) -> None:
    """Stages switching a category off/on - or drops it if it matches what's saved."""
    pending = _pending_excl()
    if excluded == saved:
        pending.pop(category_id, None)
    else:
        pending[category_id] = excluded


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
