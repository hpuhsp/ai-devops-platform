"""add agents table and repository.agent_bindings

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_now = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("stage_type", sa.String(length=50), nullable=False),
        sa.Column("skill_type", sa.String(length=20), nullable=False, server_default="builtin"),
        sa.Column("skill_name", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("ai_models.id"), nullable=True),
        sa.Column("skill_config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("model_config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("policy_config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true()),
        sa.Column("is_system", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now),
    )
    op.create_index("ix_agents_stage_type", "agents", ["stage_type"])

    op.add_column(
        "repositories",
        sa.Column("agent_bindings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("repositories", "agent_bindings")
    op.drop_index("ix_agents_stage_type", table_name="agents")
    op.drop_table("agents")
