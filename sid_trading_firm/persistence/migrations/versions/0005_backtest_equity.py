"""Backtest equity curves: backtest_results.equity.

Revision ID: 0005_backtest_equity
Revises: 0004_screening
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_backtest_equity"
down_revision = "0004_screening"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("backtest_results", sa.Column("equity", JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("backtest_results") as batch:
        batch.drop_column("equity")
