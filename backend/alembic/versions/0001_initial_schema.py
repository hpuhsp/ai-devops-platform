"""initial schema

Mirrors the SQLAlchemy models under app/models at the time Alembic was introduced.
For DEBUG/local runs the app still auto-creates tables via Base.metadata.create_all;
for any other environment run `alembic upgrade head`.

Revision ID: 0001
Revises:
Create Date: 2026-06-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_now = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "ai_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("api_base", sa.String(length=500)),
        sa.Column("api_key_encrypted", sa.Text()),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false()),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now),
    )

    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("repo_url", sa.String(length=500), nullable=False),
        sa.Column("webhook_secret", sa.String(length=200)),
        sa.Column("git_token_encrypted", sa.Text()),
        sa.Column("branch_rules", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("ai_model_id", sa.Integer(), sa.ForeignKey("ai_models.id"), nullable=True),
        sa.Column("skills_config", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now),
    )
    op.create_index("ix_repositories_platform_enabled", "repositories", ["platform", "enabled"])

    op.create_table(
        "pipeline_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.Integer(),
                  sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("pattern", sa.String(length=200), nullable=False),
        sa.Column("stages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
    )
    op.create_index("ix_pipeline_rules_repo_id", "pipeline_rules", ["repo_id"])

    op.create_table(
        "ai_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=100), nullable=False, unique=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=True),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger_event", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("input_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("output_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("error_message", sa.Text()),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), server_default="0"),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now),
    )
    op.create_index("ix_ai_tasks_repo_id", "ai_tasks", ["repo_id"])
    op.create_index("ix_ai_tasks_status", "ai_tasks", ["status"])
    op.create_index("ix_ai_tasks_created_at", "ai_tasks", ["created_at"])

    op.create_table(
        "notify_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
    )

    op.create_table(
        "stats_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("metric_type", sa.String(length=50), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
        sa.UniqueConstraint("date", "metric_type", "dimensions", name="uq_stats_snapshot"),
    )

    op.create_table(
        "jenkins_builds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_name", sa.String(length=200), nullable=False),
        sa.Column("build_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("repo_url", sa.String(length=500)),
        sa.Column("triggered_by", sa.String(length=100)),
        sa.Column("build_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
    )


def downgrade() -> None:
    op.drop_table("jenkins_builds")
    op.drop_table("stats_snapshots")
    op.drop_table("notify_configs")
    op.drop_index("ix_ai_tasks_created_at", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_status", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_repo_id", table_name="ai_tasks")
    op.drop_table("ai_tasks")
    op.drop_index("ix_pipeline_rules_repo_id", table_name="pipeline_rules")
    op.drop_table("pipeline_rules")
    op.drop_index("ix_repositories_platform_enabled", table_name="repositories")
    op.drop_table("repositories")
    op.drop_table("ai_models")
