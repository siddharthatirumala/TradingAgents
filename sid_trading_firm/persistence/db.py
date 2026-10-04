"""Engine and session handling. The connection URL comes from settings, never from code."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sid_trading_firm.config.settings import Settings
from sid_trading_firm.persistence.sanitize import sanitize_pending_rows


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """An engine for ``url``. SQLite (unit tests) gets foreign keys enforced like PostgreSQL."""
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite+pysqlite://"):
            kwargs["poolclass"] = StaticPool      # one shared in-memory database
        engine = create_engine(url, echo=echo, **kwargs)

        @event.listens_for(engine, "connect")
        def _foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(url, echo=echo, pool_pre_ping=True)


def engine_from_settings(settings: Settings) -> Engine:
    return make_engine(settings.database.require_url(), echo=settings.database.echo)


class Database:
    """A session factory with commit-or-rollback scopes.

    Every session it makes masks credentials in diagnostic columns before each
    flush (``persistence.sanitize``), so no write path can store one.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        event.listen(self._sessions, "before_flush", sanitize_pending_rows)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
