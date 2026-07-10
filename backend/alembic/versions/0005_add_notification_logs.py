"""add notification logs

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_now = sa.text("now()")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("notification_logs"):
        op.create_table(
            "notification_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.String(length=100), sa.ForeignKey("ai_tasks.task_id"), nullable=True),
            sa.Column("notify_config_id", sa.Integer(), sa.ForeignKey("notify_configs.id"), nullable=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("target", sa.String(length=200)),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.String(length=300)),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text())),
            sa.Column("error", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("notification_logs")}
    if "ix_notification_logs_task_id" not in existing_indexes:
        op.create_index("ix_notification_logs_task_id", "notification_logs", ["task_id"])
    if "ix_notification_logs_notify_config_id" not in existing_indexes:
        op.create_index("ix_notification_logs_notify_config_id", "notification_logs", ["notify_config_id"])
    if "ix_notification_logs_event_type" not in existing_indexes:
        op.create_index("ix_notification_logs_event_type", "notification_logs", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_notification_logs_event_type", table_name="notification_logs")
    op.drop_index("ix_notification_logs_notify_config_id", table_name="notification_logs")
    op.drop_index("ix_notification_logs_task_id", table_name="notification_logs")
    op.drop_table("notification_logs")
