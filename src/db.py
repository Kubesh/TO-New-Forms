import os
from contextlib import contextmanager

import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()


def normalize_database_url(url: str) -> str:
    """Force the psycopg (v3) driver regardless of the scheme the URL was copied with."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


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
