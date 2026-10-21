from src.models import Category

FALLBACK_COLOR = "rgba(128, 128, 128, 0.35)"


def category_color(category: Category | None) -> str:
    """A category's card-indicator color - always the top-level ancestor's
    color (subcategories and sub sub categories don't carry their own), falling
    back to a neutral gray for anything uncategorized or not yet given a
    color."""
    if category is None:
        return FALLBACK_COLOR
    top_level = category
    while top_level.parent is not None:
        top_level = top_level.parent
    return top_level.color or FALLBACK_COLOR
