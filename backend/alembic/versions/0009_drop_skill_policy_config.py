"""drop skill_config and policy_config from agents

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for col in ("skill_config", "policy_config"):
        if _has_column(inspector, "agents", col):
            op.drop_column("agents", col)


def downgrade() -> None:
    from sqlalchemy.dialects import postgresql

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "agents", "policy_config"):
        op.add_column("agents", sa.Column("policy_config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")))
    if not _has_column(inspector, "agents", "skill_config"):
        op.add_column("agents", sa.Column("skill_config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")))
