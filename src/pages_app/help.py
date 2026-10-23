import streamlit as st

from src.db import session_scope
from src.services.help_pages import MAX_HELP_LENGTH, get_help_page, save_help_page


def render_help_button(page_key: str, page_title: str) -> None:
    """The "Help" button pinned to the top right (positioned in app.py's CSS);
    opens the help for this page, keyed by its URL path."""
    with st.container(key="tp-help-button"):
        if st.button("Help", key="tp_help_btn"):
            help_dialog(page_key, page_title)


@st.dialog("Help", width="large")
def help_dialog(page_key: str, page_title: str) -> None:
    editing_key = f"help_editing_{page_key}"
    try:
        with session_scope() as session:
            page = get_help_page(session, page_key)
            content = page.content if page else ""
            updated_at = page.updated_at if page else None
    except Exception:
        st.error("Help isn't available right now - the help table may not be set up yet.")
        return

    st.subheader(page_title)
    if st.session_state.get(editing_key):
        text = st.text_area(
            "Help text (Markdown)",
            height=360,
            max_chars=MAX_HELP_LENGTH,
            key=f"help_text_{page_key}",
            help="Supports Markdown: # headings, **bold**, - lists, [links](https://...), tables.",
        )
        col_save, col_cancel, _ = st.columns([1, 1, 3])
        with col_save:
            if st.button("Save", type="primary", width="stretch", key=f"help_save_{page_key}"):
                try:
                    with session_scope() as session:
                        save_help_page(session, page_key, text)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state[editing_key] = False
                    st.rerun(scope="fragment")
        with col_cancel:
            if st.button("Cancel", width="stretch", key=f"help_cancel_{page_key}"):
                st.session_state[editing_key] = False
                st.rerun(scope="fragment")
        return

    if content:
        st.markdown(content)
        if updated_at:
            st.caption(f"Last edited {updated_at.strftime('%m/%d/%Y %I:%M %p')}")
    else:
        st.info("No help has been written for this page yet.")
    if st.button("Edit", key=f"help_edit_{page_key}"):
        # Start the editor from what's saved, not from an earlier cancelled edit.
        st.session_state[f"help_text_{page_key}"] = content
        st.session_state[editing_key] = True
        st.rerun(scope="fragment")
