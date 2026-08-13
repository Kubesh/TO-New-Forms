import streamlit as st

from src.pages_app.customers import customers_page
from src.pages_app.items import items_page
from src.pages_app.purchase_orders import purchase_orders_page

st.set_page_config(
    page_title="Treehouse Originals",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Keep the sidebar permanently open (no collapse/expand control), drop the
# '#' anchor-link icons Streamlit adds to headers on hover, and layer on the
# brand touches the native theme (.streamlit/config.toml) can't reach:
# uppercase/letter-spaced nav and headings, and the bold 2px black borders
# from the Treehouse Originals style guide.
st.markdown(
    """
    <style>
    /* Futura is the real Treehouse Originals brand font, so it's first in
    the stack for users who have it (most Macs ship it as a system font).
    Everyone else falls through to Source Sans, Streamlit's own bundled
    font - not Poppins. Streamlit's markdown sanitizer strips <link> tags,
    and a CSS @import doesn't get processed when injected into a <style>
    tag this way (a browser quirk: @import is only honored on a style
    element's first parse, not on a later content update, which is how
    React/Streamlit sets this markdown block's HTML), so there's no way to
    pull in a Google-hosted Poppins fallback from here. */
    html, body, .stApp, [class^="st-"], [class*=" st-"] {
        font-family: Futura, "Futura PT", "Source Sans", sans-serif !important;
    }
    [data-testid="stSidebarCollapseButton"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    [data-testid="stSidebar"] {
        transform: none !important;
        visibility: visible !important;
        min-width: 244px !important;
        border-right: 2px solid #1A1712 !important;
    }
    [data-testid="stHeaderActionElements"] { display: none !important; }
    [data-testid="stMainBlockContainer"] {
        max-width: 65% !important;
    }
    h1, h2, h3 {
        text-transform: uppercase;
        letter-spacing: 0.01em;
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] {
        border-radius: 8px;
        text-transform: uppercase;
        font-weight: 600;
        font-size: 0.85rem;
        letter-spacing: 0.03em;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

customers = st.Page(customers_page, title="Customers", url_path="customers", default=True)
purchase_orders = st.Page(
    purchase_orders_page, title="Purchase Orders", url_path="purchase-orders"
)
items = st.Page(items_page, title="Items", url_path="items")

# Build the nav ourselves (position="hidden") so the sidebar always renders,
# rather than relying on Streamlit's auto nav widget, which hides itself
# whenever there's only a single page.
pg = st.navigation(
    {"Customers": [customers], "Purchase Orders": [purchase_orders], "Items": [items]},
    position="hidden",
)

with st.sidebar:
    st.page_link(customers, label="Customers")
    st.page_link(purchase_orders, label="Purchase Orders")
    st.page_link(items, label="Items")

pg.run()
