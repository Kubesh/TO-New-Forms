FALLBACK_COLOR = "rgba(128, 128, 128, 0.35)"


def category_color(category: str | None, color_map: dict[str, str]) -> str:
    """A category's card-indicator color, as set on its Category row -
    falls back to a neutral gray for anything uncategorized, or any
    category string that doesn't (yet) have a managed row/color."""
    if not category:
        return FALLBACK_COLOR
    return color_map.get(category, FALLBACK_COLOR)
