"""drop notification_policies table

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "notification_policies"):
        op.drop_index("ix_np_enabled", table_name="notification_policies")
        op.drop_index("ix_np_notify_config_id", table_name="notification_policies")
        op.drop_table("notification_policies")


def downgrade() -> None:
    from sqlalchemy.dialects import postgresql

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "notification_policies"):
        op.create_table(
            "notification_policies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("repo_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("branch_patterns", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("event_types", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("stage_types", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("status_filter", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("min_severity", sa.String(20), server_default="all"),
            sa.Column("blocked_only", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("notify_config_id", sa.Integer(), sa.ForeignKey("notify_configs.id"), nullable=True),
            sa.Column("targets", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true")),
            sa.Column("priority", sa.Integer(), server_default=sa.text("50")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_np_notify_config_id", "notification_policies", ["notify_config_id"])
        op.create_index("ix_np_enabled", "notification_policies", ["enabled"])
