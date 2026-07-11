"""add notification policies

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_now = sa.text("now()")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("notification_policies"):
        op.create_table(
            "notification_policies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("repo_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("branch_patterns", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("event_types", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("stage_types", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("status_filter", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("min_severity", sa.String(length=20), server_default=sa.text("'all'")),
            sa.Column("blocked_only", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("notify_config_id", sa.Integer(), sa.ForeignKey("notify_configs.id"), nullable=True),
            sa.Column("targets", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true")),
            sa.Column("priority", sa.Integer(), server_default=sa.text("50")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("notification_policies")}
    if "ix_np_notify_config_id" not in existing_indexes:
        op.create_index("ix_np_notify_config_id", "notification_policies", ["notify_config_id"])
    if "ix_np_enabled" not in existing_indexes:
        op.create_index("ix_np_enabled", "notification_policies", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_np_enabled", table_name="notification_policies")
    op.drop_index("ix_np_notify_config_id", table_name="notification_policies")
    op.drop_table("notification_policies")
