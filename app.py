from pathlib import Path

import streamlit as st

from src.pages_app.categories import categories_page
from src.pages_app.customers import customers_page
from src.pages_app.inventory import inventory_page
from src.pages_app.items import items_page
from src.pages_app.purchase_orders import purchase_orders_page

st.set_page_config(
    page_title="Treehouse Originals",
    page_icon=str(Path(__file__).parent / "static" / "images" / "treehouse-logo.png"),
    layout="wide",
    # "locked" keeps the sidebar permanently open with no collapse control on
    # desktop (the old always-open behavior), but degrades gracefully on
    # narrow/mobile viewports: starts collapsed there, with a hamburger button
    # to open it and a close button inside it to dismiss it, rather than
    # permanently covering the main content on a small screen.
    initial_sidebar_state="locked",
)

# Drop the '#' anchor-link icons Streamlit adds to headers on hover, and
# layer on the brand touches the native theme (.streamlit/config.toml) can't
# reach: uppercase/letter-spaced nav and headings, the bold 2px black
# borders from the Treehouse Originals style guide, and a full-width
# sidebar on mobile (its native "locked" mobile width is comfortable but
# not full-screen).
st.markdown(
    """
    <style>
    /* Futura PT is the real Treehouse Originals brand font, licensed and
    supplied by Treehouse - the actual font files live in static/fonts/ and
    load via [[theme.fontFaces]] in .streamlit/config.toml (which also sets
    this as the theme's font/headingFont; this override exists because a
    handful of Streamlit's own emotion-styled subcomponents hardcode their
    own font-family instead of inheriting the theme's). */
    html, body, .stApp, [class^="st-"], [class*=" st-"] {
        font-family: "Futura PT", "Source Sans", sans-serif !important;
    }
    /* The broad override above also catches Streamlit's icon-font glyphs
    (the sidebar hamburger/close arrows, etc.), which render via ligature
    text in a dedicated icon font - forcing our brand font onto them shows
    literal text like "keyboard_double_arrow_right" instead of the icon.
    Rather than depend on that icon font loading/rendering correctly at
    all, hide its ligature text and draw explicit hamburger/X characters
    instead - simple, unambiguous, and immune to font-loading issues. */
    [data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"],
    [data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"] {
        font-size: 0 !important;
    }
    [data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"]::before {
        content: "\\2630";
        font-size: 1.35rem;
        font-family: initial !important;
        line-height: 1;
    }
    [data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"]::before {
        content: "\\2715";
        font-size: 1.15rem;
        font-family: initial !important;
        line-height: 1;
    }
    [data-testid="stSidebar"] {
        border-right: 2px solid #1A1712 !important;
    }
    @media (min-width: 768px) {
        [data-testid="stSidebar"] {
            min-width: 244px !important;
        }
        [data-testid="stMainBlockContainer"] {
            max-width: 65% !important;
        }
        /* The PO create/edit forms use st.dialog(width="large"), which
        Streamlit renders at a fixed 1120px - max-width (rather than width)
        only kicks in when that's wider than our target, so the smaller
        "small"-width dialogs (delete confirm, manage shipping materials)
        are left alone. 1120 * 0.75 = 840. */
        [data-testid="stDialog"] > div {
            max-width: 840px !important;
        }
    }
    @media (max-width: 767px) {
        /* Only the expanded state is widened to fill the screen - the
        collapsed state is left alone entirely. The hamburger-to-close
        toggle button lives inside the sidebar and moves with it, so
        overriding the collapsed width/transform too (to make it wider)
        pushes that same button off-screen with the rest of the panel,
        leaving no way to reopen it. */
        [data-testid="stSidebar"][aria-expanded="true"] {
            width: 100vw !important;
            min-width: 100vw !important;
            transform: translateX(0) !important;
        }
    }
    [data-testid="stHeaderActionElements"] { display: none !important; }
    /* Deploy button and the "⋮" menu (Rerun/Settings/Clear cache/About)
    are removed via client.toolbarMode = "minimal" in
    .streamlit/config.toml, not CSS - that also stops Clear cache's "C"
    keyboard shortcut from registering at all, which CSS alone can't do
    (it was still intercepting Cmd/Ctrl+C before this). */
    /* The running-script indicator (a little running-man icon plus a
    "Stop" button) normally docks in the top-right header. Recenter its
    container on the viewport, then swap its default icon/button for a
    spinning version of the brand mark - it's now purely a "hang on"
    signal rather than an interactive stop control. display is
    deliberately left alone here - Streamlit toggles it (inline, no
    !important) to actually hide this element once the script finishes,
    and a forced !important display would win that fight and leave it
    stuck on screen permanently. */
    [data-testid="stStatusWidget"] {
        position: fixed !important;
        top: 50% !important;
        left: 50% !important;
        transform: translate(-50%, -50%) !important;
        z-index: 9999 !important;
        width: 56px !important;
        height: 56px !important;
        padding: 0 !important;
        margin: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        border: none !important;
        pointer-events: none !important;
    }
    [data-testid="stStatusWidget"] > div {
        display: none !important;
    }
    [data-testid="stStatusWidget"]::before {
        content: "";
        display: block;
        width: 100%;
        height: 100%;
        background-image: url('/app/static/images/treehouse-logo.png');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        animation: tp-logo-spin 1s linear infinite;
    }
    @keyframes tp-logo-spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
    /* The auto-close/favicon helper below runs in a 1px-tall iframe so it's
    invisible, but on iOS Safari a scrollable iframe (even a hidden one)
    can show its native scroll-indicator pill floating in the sidebar -
    overflow:hidden here stops that at the source. */
    [data-testid="stIFrame"] {
        overflow: hidden !important;
        pointer-events: none !important;
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
    .st-key-tp-sidebar-subnav [data-testid="stPageLink"] {
        margin-left: 1.1rem;
        font-size: 0.78rem;
    }
    .tp-sidebar-brand {
        padding-bottom: 1rem;
        margin-bottom: 0.75rem;
        border-bottom: 2px solid #1A1712;
    }
    .tp-sidebar-brand-row {
        display: flex;
        align-items: center;
        gap: 0.6rem;
    }
    .tp-sidebar-brand-logo {
        width: 34px;
        height: 34px;
        flex: none;
    }
    .tp-sidebar-brand-name {
        font-weight: 800;
        font-size: 1rem;
        text-transform: uppercase;
        letter-spacing: 0.01em;
        line-height: 1.15;
    }
    .tp-sidebar-brand-sub {
        font-weight: 700;
        font-size: 0.7rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #F4591A;
        margin-top: 0.15rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

customers = st.Page(customers_page, title="Customers", url_path="customers", default=True)
purchase_orders = st.Page(
    purchase_orders_page, title="Purchase Orders", url_path="purchase-orders"
)
inventory = st.Page(inventory_page, title="Inventory", url_path="inventory")
categories = st.Page(categories_page, title="Categories", url_path="categories")
items = st.Page(items_page, title="Items", url_path="items")

# Build the nav ourselves (position="hidden") so the sidebar always renders,
# rather than relying on Streamlit's auto nav widget, which hides itself
# whenever there's only a single page.
pg = st.navigation(
    {
        "Customers": [customers],
        "Purchase Orders": [purchase_orders],
        "Inventory": [inventory, categories],
        "Items": [items],
    },
    position="hidden",
)

with st.sidebar:
    st.markdown(
        '<div class="tp-sidebar-brand">'
        '<div class="tp-sidebar-brand-row">'
        '<img class="tp-sidebar-brand-logo" src="app/static/images/treehouse-logo.png" '
        'alt="Treehouse Originals">'
        "<div>"
        '<div class="tp-sidebar-brand-name">Treehouse Originals</div>'
        '<div class="tp-sidebar-brand-sub">Operations</div>'
        "</div>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.page_link(customers, label="Customers")
    st.page_link(purchase_orders, label="Purchase Orders")
    st.page_link(inventory, label="Inventory")
    with st.container(key="tp-sidebar-subnav"):
        st.page_link(categories, label="Categories")
    st.page_link(items, label="Items")

    # Streamlit's page navigation is a client-side transition, not a full
    # page reload, so the sidebar's open/closed state survives it - on
    # mobile that means clicking a nav link leaves the sidebar covering
    # whichever page you just navigated to. There's no Python-level API for
    # sidebar collapse state, so this reaches into the parent document from
    # a same-origin iframe (allowed - see st.iframe's warning about this)
    # and clicks the native close button itself after a nav-link click, but
    # only on narrow/mobile viewports - desktop has no close button to
    # click, and the width check short-circuits before ever looking for one
    # there.
    #
    # It also fixes the favicon: st.set_page_config(page_icon=...) only
    # works for a local file when Streamlit's MediaFileManager is available
    # to register it, which isn't reliably the case at page-config time, so
    # it silently falls back to Streamlit's own icon instead of raising.
    # Setting the <link rel="icon"> directly here is a guaranteed override.
    st.iframe(
        """
        <style>
        html, body { margin: 0; padding: 0; overflow: hidden; }
        </style>
        <script>
        (function () {
            const doc = window.parent.document;
            let iconLink = doc.querySelector('link[rel~="icon"]');
            if (!iconLink) {
                iconLink = doc.createElement('link');
                iconLink.rel = 'icon';
                doc.head.appendChild(iconLink);
            }
            iconLink.type = 'image/png';
            iconLink.href = '/app/static/images/treehouse-logo.png';

            if (window.parent.__tpSidebarAutoClose) return;
            window.parent.__tpSidebarAutoClose = true;
            doc.addEventListener('click', function (e) {
                if (window.parent.innerWidth >= 768) return;
                const link = e.target.closest(
                    '[data-testid="stSidebar"] [data-testid="stPageLink"] a'
                );
                if (!link) return;
                setTimeout(function () {
                    const closeBtn = doc.querySelector(
                        '[data-testid="stSidebarCollapseButton"] button'
                    );
                    if (closeBtn) closeBtn.click();
                }, 100);
            }, true);
        })();
        </script>
        """,
        height=1,
    )

pg.run()
