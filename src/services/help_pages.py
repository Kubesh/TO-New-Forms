from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models import HelpPage

MAX_HELP_LENGTH = 50000


def get_help_page(session: Session, page_key: str) -> HelpPage | None:
    return session.get(HelpPage, page_key)


def save_help_page(session: Session, page_key: str, content: str) -> None:
    """Saves a page's help text; blank text removes it."""
    content = (content or "").strip()
    if len(content) > MAX_HELP_LENGTH:
        raise ValueError(f"Help text is limited to {MAX_HELP_LENGTH:,} characters.")
    existing = session.get(HelpPage, page_key)
    if not content:
        if existing is not None:
            session.delete(existing)
    elif existing is None:
        session.add(HelpPage(page_key=page_key, content=content))
    else:
        existing.content = content
        existing.updated_at = func.now()
    session.commit()
