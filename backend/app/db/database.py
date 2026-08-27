"""SQLAlchemy engine, session factory and schema creation.

Sync engine on SQLite, per CLAUDE.md Section 3: at this scale async adds complexity and
buys nothing, and a single-file database keeps "clone and run" honest.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_ROOT, get_settings

logger = logging.getLogger("recourse.db")


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def _resolve_url() -> str:
    """Resolve DATABASE_URL, anchoring a relative SQLite path to backend/.

    Without this, `sqlite:///./recourse.db` would create a different database file
    depending on the directory uvicorn or pytest happened to be started from -- a
    genuinely confusing bug where seeded data appears to vanish.
    """
    url = get_settings().database_url
    prefix = "sqlite:///./"
    if url.startswith(prefix):
        return f"sqlite:///{(BACKEND_ROOT / url[len(prefix):]).as_posix()}"
    return url


engine = create_engine(
    _resolve_url(),
    # SQLite defaults to rejecting cross-thread use; FastAPI serves requests on a
    # threadpool, so each session must be allowed to travel.
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    """SQLite ignores FOREIGN KEY constraints unless told otherwise, per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _add_missing_columns() -> None:
    """Add columns the ORM declares but the existing database file lacks.

    `create_all` only creates missing TABLES -- it will not alter one that already exists.
    So every time a column was added to a model, the running database silently went stale
    and the fix was to delete recourse.db, which also threw away every decision and audit
    entry recorded against it. For an app that argues its audit trail is the point, losing
    the audit trail to a schema change is not an acceptable upgrade path.

    This closes that gap for the only schema change SQLite handles cheaply and safely:
    adding a nullable/defaulted column. Anything harder -- dropping a column, changing a
    type, adding a constraint -- is deliberately NOT attempted here; it needs a real
    migration tool, and silently half-doing it would be worse than failing loudly.
    """
    from sqlalchemy import inspect as sa_inspect, text

    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all just made it; it is already current
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not (column.nullable or column.default is not None or column.server_default):
                    logger.error(
                        "column %s.%s is missing and is NOT NULL without a default; "
                        "this needs a manual migration",
                        table.name,
                        column.name,
                    )
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(engine.dialect)}"
                connection.execute(text(ddl))
                logger.warning("migrated: added %s.%s", table.name, column.name)


def init_db() -> None:
    """Create any missing tables and columns. Safe to call repeatedly."""
    from app.db import models  # noqa: F401  -- registers models on Base.metadata

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    logger.info("database ready at %s", engine.url)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session and always closing it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and tests: commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = ["Base", "SessionLocal", "engine", "get_session", "init_db", "session_scope"]
