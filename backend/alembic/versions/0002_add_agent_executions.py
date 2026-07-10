"""add agent_executions table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_now = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=100),
                  sa.ForeignKey("ai_tasks.task_id"), nullable=False),
        sa.Column("agent_type", sa.String(length=50), nullable=False),
        sa.Column("round_number", sa.Integer(), server_default="1"),
        sa.Column("input_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("output_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), server_default="0"),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
    )
    op.create_index("ix_agent_executions_task_id", "agent_executions", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_executions_task_id", table_name="agent_executions")
    op.drop_table("agent_executions")
