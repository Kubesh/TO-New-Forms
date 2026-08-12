import os
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

# Fail fast instead of hanging indefinitely (e.g. on networks where IPv6
# routes to the DB host are black-holed).
DEFAULT_CONNECT_TIMEOUT_SECONDS = "10"


def normalize_database_url(url: str) -> str:
    """Force the psycopg (v3) driver and a connect timeout, regardless of how
    the URL was copied (scheme, existing query params, etc.)."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.setdefault("connect_timeout", DEFAULT_CONNECT_TIMEOUT_SECONDS)
    return urlunsplit(parts._replace(query=urlencode(query)))


@st.cache_resource
def get_engine():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and add your Neon "
            "connection string."
        )
    return create_engine(normalize_database_url(database_url), pool_pre_ping=True)


@contextmanager
def session_scope() -> Session:
    Session_ = sessionmaker(bind=get_engine())
    session = Session_()
    try:
        yield session
    finally:
        session.close()
