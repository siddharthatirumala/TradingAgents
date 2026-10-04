"""Initial schema: research_runs, llm_usage, audit_events.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("instrument", sa.String(16), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("strategy", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upstream_version", sa.String(32), nullable=False),
        sa.Column("code_version", sa.String(64), nullable=True),
        sa.Column("config_snapshot", JSONType, nullable=False),
        sa.Column("summary", JSONType, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('running', 'completed', 'budget_stopped', 'failed')",
                           name=op.f("ck_research_runs_status")),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_research_runs")),
    )
    op.create_index(op.f("ix_research_runs_started_at"), "research_runs", ["started_at"])
    op.create_index(op.f("ix_research_runs_instrument_trade_date"), "research_runs",
                    ["instrument", "trade_date"])

    op.create_table(
        "llm_usage",
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("node", sa.String(128), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=True),
        sa.Column("usage_available", sa.Boolean(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column("cost_status", sa.String(16), nullable=False),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False),
        sa.Column("prompt_chars", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.run_id"], ondelete="RESTRICT",
                                name=op.f("fk_llm_usage_run_id_research_runs")),
        sa.PrimaryKeyConstraint("call_id", name=op.f("pk_llm_usage")),
    )
    op.create_index(op.f("ix_llm_usage_run_id"), "llm_usage", ["run_id"])
    op.create_index(op.f("ix_llm_usage_started_at"), "llm_usage", ["started_at"])
    op.create_index(op.f("ix_llm_usage_agent"), "llm_usage", ["agent"])

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", JSONType, nullable=True),
        sa.CheckConstraint("severity IN ('debug', 'info', 'warning', 'error', 'critical')",
                           name=op.f("ck_audit_events_severity")),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.run_id"], ondelete="RESTRICT",
                                name=op.f("fk_audit_events_run_id_research_runs")),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_run_id"), "audit_events", ["run_id"])
    op.create_index(op.f("ix_audit_events_event_type_occurred_at"), "audit_events",
                    ["event_type", "occurred_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("llm_usage")
    op.drop_table("research_runs")
