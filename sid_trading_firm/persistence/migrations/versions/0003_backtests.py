"""Backtest records: strategy_versions and backtest_results.

Revision ID: 0003_backtests
Revises: 0002_llm_usage_call_details
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_backtests"
down_revision = "0002_llm_usage_call_details"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
STATUSES = "('PROPOSED', 'BACKTESTED', 'VALIDATED', 'PAPER_APPROVED', 'PAPER_ACTIVE', 'RETIRED')"
SEGMENTS = "('full', 'train', 'validation', 'test', 'walk_forward_window', 'walk_forward_oos')"


def upgrade() -> None:
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identifier", sa.String(64), nullable=False),
        sa.Column("params", JSONType, nullable=False),
        sa.Column("params_hash", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN {STATUSES}", name=op.f("ck_strategy_versions_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_versions")),
        sa.UniqueConstraint("identifier", "params_hash", name=op.f("uq_strategy_versions_identifier_params_hash")),
    )
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_version_id", sa.Uuid(), nullable=False),
        sa.Column("segment", sa.String(24), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("data_fingerprint", sa.String(32), nullable=False),
        sa.Column("data_source", sa.String(128), nullable=False),
        sa.Column("config", JSONType, nullable=False),
        sa.Column("metrics", JSONType, nullable=False),
        sa.Column("regimes", JSONType, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"segment IN {SEGMENTS}", name=op.f("ck_backtest_results_segment")),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.run_id"], ondelete="RESTRICT",
                                name=op.f("fk_backtest_results_run_id_research_runs")),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"], ondelete="RESTRICT",
                                name=op.f("fk_backtest_results_strategy_version_id_strategy_versions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_results")),
    )
    op.create_index(op.f("ix_backtest_results_run_id"), "backtest_results", ["run_id"])
    op.create_index(op.f("ix_backtest_results_strategy_version_id"), "backtest_results", ["strategy_version_id"])


def downgrade() -> None:
    op.drop_table("backtest_results")
    op.drop_table("strategy_versions")
