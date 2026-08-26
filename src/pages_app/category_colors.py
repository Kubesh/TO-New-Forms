CATEGORY_PALETTE = [
    "#F4591A",  # orange
    "#1D4ED8",  # blue
    "#059669",  # green
    "#7C3AED",  # violet
    "#B45309",  # amber
    "#DB2777",  # pink
    "#0891B2",  # cyan
    "#65A30D",  # lime
    "#DC2626",  # red
    "#4338CA",  # indigo
]


def category_color(category: str | None, sorted_categories: list[str]) -> str:
    """A stable color per category, keyed by its position in the full
    (unfiltered) sorted category list - so a given category always maps to
    the same color everywhere it's shown, regardless of what's filtered
    into view on any particular page."""
    if not category or category not in sorted_categories:
        return "rgba(128, 128, 128, 0.35)"
    return CATEGORY_PALETTE[sorted_categories.index(category) % len(CATEGORY_PALETTE)]
