"""Lifetime AI budget: budget_reservations.

Revision ID: 0006_budget_reservations
Revises: 0005_backtest_equity
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_budget_reservations"
down_revision = "0005_backtest_equity"
branch_labels = None
depends_on = None

STATUSES = "('open', 'settled', 'released')"


def upgrade() -> None:
    op.create_table(
        "budget_reservations",
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(14, 8), nullable=False),
        sa.Column("assumed_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN {STATUSES}", name=op.f("ck_budget_reservations_status")),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.run_id"], ondelete="RESTRICT",
                                name=op.f("fk_budget_reservations_run_id_research_runs")),
        sa.PrimaryKeyConstraint("call_id", name=op.f("pk_budget_reservations")),
    )
    op.create_index(op.f("ix_budget_reservations_status"), "budget_reservations", ["status"])


def downgrade() -> None:
    op.drop_table("budget_reservations")
