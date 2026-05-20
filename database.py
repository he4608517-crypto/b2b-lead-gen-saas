"""
Database engine and session management for the B2B Lead Gen SaaS.

Uses SQLite with WAL mode for concurrent read/write access.
Every table has a tenant_id foreign key to enforce multi-tenancy.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "b2b_saas.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Enable WAL mode for better concurrency
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


@contextmanager
def get_db() -> Session:
    """Yield a database session and close it after use."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Create all tables if they do not exist."""
    from models import Base
    Base.metadata.create_all(bind=engine)
