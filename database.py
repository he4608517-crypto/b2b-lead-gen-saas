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


def _migrate_users_smtp_columns():
    """Add per-tenant SMTP columns if the users table predates them."""
    import sqlite3

    try:
        conn = sqlite3.connect(DB_PATH)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        needed = {
            "smtp_host": "VARCHAR(255) DEFAULT ''",
            "smtp_port": "INTEGER DEFAULT 0",
            "smtp_username": "VARCHAR(255) DEFAULT ''",
            "smtp_password": "VARCHAR(255) DEFAULT ''",
        }
        for col, typedef in needed.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
        conn.commit()
        conn.close()
    except Exception:
        pass  # table doesn't exist yet — create_all will handle it


def init_db():
    """Create all tables if they do not exist, then run migrations."""
    from models import Base
    Base.metadata.create_all(bind=engine)
    _migrate_users_smtp_columns()
