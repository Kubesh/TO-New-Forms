import streamlit as st

from src.pages_app.customers import customers_page

st.set_page_config(
    page_title="Treehouse Originals",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Keep the sidebar permanently open (no collapse/expand control), and drop
# the '#' anchor-link icons that Streamlit adds to headers on hover.
st.markdown(
    """
    <style>
    [data-testid="stSidebarCollapseButton"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    [data-testid="stSidebar"] {
        transform: none !important;
        visibility: visible !important;
        min-width: 244px !important;
    }
    [data-testid="stHeaderActionElements"] { display: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

customers = st.Page(customers_page, title="Customers", icon="📇", url_path="customers", default=True)

# Build the nav ourselves (position="hidden") so the sidebar always renders,
# rather than relying on Streamlit's auto nav widget, which hides itself
# whenever there's only a single page.
pg = st.navigation({"Customers": [customers]}, position="hidden")

with st.sidebar:
    st.page_link(customers, label="Customers", icon="📇")

pg.run()
