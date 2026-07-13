"""drop unused agent config columns

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for col in ("instructions", "skills", "mcp_tools", "guardrails", "model_config"):
        if _has_column(inspector, "agents", col):
            op.drop_column("agents", col)


def downgrade() -> None:
    from sqlalchemy.dialects import postgresql

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "agents", "model_config"):
        op.add_column("agents", sa.Column("model_config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")))
    if not _has_column(inspector, "agents", "guardrails"):
        op.add_column("agents", sa.Column("guardrails", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")))
    if not _has_column(inspector, "agents", "mcp_tools"):
        op.add_column("agents", sa.Column("mcp_tools", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")))
    if not _has_column(inspector, "agents", "skills"):
        op.add_column("agents", sa.Column("skills", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")))
    if not _has_column(inspector, "agents", "instructions"):
        op.add_column("agents", sa.Column("instructions", sa.Text(), nullable=True))
