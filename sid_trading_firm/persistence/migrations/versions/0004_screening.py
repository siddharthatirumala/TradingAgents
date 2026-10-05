"""Screening records: screening_results and screening_candidates.

Revision ID: 0004_screening
Revises: 0003_backtests
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_screening"
down_revision = "0003_backtests"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "screening_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("universe", sa.String(128), nullable=False),
        sa.Column("universe_fingerprint", sa.String(32), nullable=False),
        sa.Column("data_fingerprint", sa.String(32), nullable=False),
        sa.Column("config_fingerprint", sa.String(32), nullable=False),
        sa.Column("inputs_fingerprint", sa.String(32), nullable=False),
        sa.Column("data_source", sa.String(128), nullable=False),
        sa.Column("config", JSONType, nullable=False),
        sa.Column("funnel", JSONType, nullable=False),
        sa.Column("rejections", JSONType, nullable=False),
        sa.Column("cost", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.run_id"], ondelete="RESTRICT",
                                name=op.f("fk_screening_results_run_id_research_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screening_results")),
    )
    op.create_index(op.f("ix_screening_results_run_id"), "screening_results", ["run_id"])
    op.create_index(op.f("ix_screening_results_as_of"), "screening_results", ["as_of"])
    op.create_table(
        "screening_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("screening_result_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("composite", sa.Float(), nullable=False),
        sa.Column("factor_ranks", JSONType, nullable=False),
        sa.Column("factor_values", JSONType, nullable=False),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_screening_candidates_rank")),
        sa.ForeignKeyConstraint(["screening_result_id"], ["screening_results.id"], ondelete="CASCADE",
                                name=op.f("fk_screening_candidates_screening_result_id_screening_results")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screening_candidates")),
        sa.UniqueConstraint("screening_result_id", "rank",
                            name=op.f("uq_screening_candidates_screening_result_id_rank")),
        sa.UniqueConstraint("screening_result_id", "symbol",
                            name=op.f("uq_screening_candidates_screening_result_id_symbol")),
    )
    op.create_index(op.f("ix_screening_candidates_symbol"), "screening_candidates", ["symbol"])


def downgrade() -> None:
    op.drop_table("screening_candidates")
    op.drop_table("screening_results")
