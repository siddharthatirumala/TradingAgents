"""Alembic environment for SID Trading Firm. The URL is set by ``persistence.migrate``."""

from alembic import context

from sid_trading_firm.persistence.db import make_engine
from sid_trading_firm.persistence.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            # SQLite cannot ALTER most things in place; batch mode rebuilds tables instead.
            context.configure(connection=connection, target_metadata=target_metadata,
                              render_as_batch=connection.dialect.name == "sqlite")
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
