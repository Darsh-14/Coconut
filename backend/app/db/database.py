"""SQLAlchemy engine, session factory and schema creation.

Sync engine on SQLite, per CLAUDE.md Section 3: at this scale async adds complexity and
buys nothing, and a single-file database keeps "clone and run" honest.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

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


def _scalar_default(column):
    """The literal a column defaults to, or None if it has no simple scalar default.

    Only plain scalars are handled. A callable or server-side default is deliberately not
    guessed at -- getting that wrong writes silent nonsense into every existing row.
    """
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    return default.arg


def _sql_literal(value) -> Optional[str]:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _add_missing_columns() -> None:
    """Add columns the ORM declares but the existing database file lacks, and backfill them.

    `create_all` only creates missing TABLES -- it will not alter one that already exists.
    So every time a column was added to a model, the running database silently went stale
    and the fix was to delete recourse.db, which also threw away every decision and audit
    entry recorded against it. For an app that argues its audit trail is the point, losing
    the audit trail to a schema change is not an acceptable upgrade path.

    THE BACKFILL IS NOT OPTIONAL. SQLite's ADD COLUMN fills every existing row with NULL,
    while SQLAlchemy's `default=` applies only on INSERT -- so a new non-nullable column
    lands as NULL on all historical rows, and the first read of one fails validation. That
    is exactly what happened when `withdrawn` was added to the audit log: every dispute
    with prior history started returning a 500. The DDL therefore carries a real DEFAULT,
    and existing NULLs are repaired on every startup so a database migrated by an earlier,
    less careful version of this function heals itself.

    Only additive changes are attempted. Dropping a column, changing a type or adding a
    constraint needs a real migration tool; silently half-doing it would be worse than
    failing loudly.
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
                literal = _sql_literal(_scalar_default(column))

                if column.name in present:
                    # Repair rows left NULL by an earlier migration that added the column
                    # without a default.
                    if literal is not None and not column.nullable:
                        repaired = connection.execute(
                            text(
                                f"UPDATE {table.name} SET {column.name} = {literal} "
                                f"WHERE {column.name} IS NULL"
                            )
                        ).rowcount
                        if repaired:
                            logger.warning(
                                "backfilled %s.%s on %d existing row(s)",
                                table.name,
                                column.name,
                                repaired,
                            )
                    continue

                if not (column.nullable or literal is not None or column.server_default):
                    logger.error(
                        "column %s.%s is missing and is NOT NULL without a default; "
                        "this needs a manual migration",
                        table.name,
                        column.name,
                    )
                    continue

                ddl = (
                    f"ALTER TABLE {table.name} ADD COLUMN {column.name} "
                    f"{column.type.compile(engine.dialect)}"
                )
                if literal is not None:
                    # SQLite requires a DEFAULT to add a NOT NULL column, and it is what
                    # gives existing rows a real value instead of NULL.
                    if not column.nullable:
                        ddl += " NOT NULL"
                    ddl += f" DEFAULT {literal}"
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
