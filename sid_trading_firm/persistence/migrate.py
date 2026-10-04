"""Schema migrations (Alembic), callable from code and from the command line.

    python -m sid_trading_firm.persistence.migrate upgrade      # to the latest schema
    python -m sid_trading_firm.persistence.migrate current
    python -m sid_trading_firm.persistence.migrate downgrade base

The database URL comes from settings (``SID_DATABASE__URL``) unless given.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # ConfigParser interpolation: a literal % in a password must be doubled.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def main(argv: list[str] | None = None) -> int:
    from sid_trading_firm.config import load_settings

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("upgrade", "downgrade", "current"):
        print(__doc__)
        return 2
    url = load_settings().database.require_url()
    cfg = alembic_config(url)
    if args[0] == "upgrade":
        command.upgrade(cfg, args[1] if len(args) > 1 else "head")
    elif args[0] == "downgrade":
        if len(args) < 2:
            print("downgrade needs a target revision, e.g. 'base'")
            return 2
        command.downgrade(cfg, args[1])
    else:
        command.current(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
