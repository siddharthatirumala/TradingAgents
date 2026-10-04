"""llm_usage: how each call was made (structured method, tools offered, tool calls).

Revision ID: 0002_llm_usage_call_details
Revises: 0001_initial
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_llm_usage_call_details"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("llm_usage") as batch:
        batch.add_column(sa.Column("structured_method", sa.String(32), nullable=True))
        batch.add_column(sa.Column("tools_offered", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("llm_usage") as batch:
        batch.drop_column("tool_calls")
        batch.drop_column("tools_offered")
        batch.drop_column("structured_method")
