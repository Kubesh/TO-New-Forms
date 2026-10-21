from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import AppSetting


def get_setting(session: Session, key: str) -> str | None:
    return session.scalar(select(AppSetting.value).where(AppSetting.key == key))


def get_settings(session: Session, keys: list[str]) -> dict[str, str]:
    rows = session.execute(select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(keys)))
    return {key: value for key, value in rows}


def set_setting(session: Session, key: str, value: str | None) -> None:
    """Saves a setting; None (or an empty string) removes it."""
    existing = session.get(AppSetting, key)
    if not value:
        if existing is not None:
            session.delete(existing)
    elif existing is None:
        session.add(AppSetting(key=key, value=value))
    else:
        existing.value = value
        existing.updated_at = func.now()
    session.commit()
