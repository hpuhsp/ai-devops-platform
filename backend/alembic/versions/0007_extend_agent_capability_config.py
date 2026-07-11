"""extend agent capability config

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "agents", "instructions"):
        op.add_column("agents", sa.Column("instructions", sa.Text(), nullable=True))
    if not _has_column(inspector, "agents", "skills"):
        op.add_column(
            "agents",
            sa.Column("skills", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        )
    if not _has_column(inspector, "agents", "mcp_tools"):
        op.add_column(
            "agents",
            sa.Column("mcp_tools", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        )
    if not _has_column(inspector, "agents", "guardrails"):
        op.add_column(
            "agents",
            sa.Column("guardrails", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "agents", "guardrails"):
        op.drop_column("agents", "guardrails")
    if _has_column(inspector, "agents", "mcp_tools"):
        op.drop_column("agents", "mcp_tools")
    if _has_column(inspector, "agents", "skills"):
        op.drop_column("agents", "skills")
    if _has_column(inspector, "agents", "instructions"):
        op.drop_column("agents", "instructions")
