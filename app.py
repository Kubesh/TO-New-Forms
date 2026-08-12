import streamlit as st

from src.pages_app.customers import customers_page

st.set_page_config(page_title="Treehouse Originals", page_icon="🌳", layout="wide")

customers = st.Page(customers_page, title="Customers", icon="📇", url_path="customers", default=True)

pg = st.navigation({"Customers": [customers]})
pg.run()
