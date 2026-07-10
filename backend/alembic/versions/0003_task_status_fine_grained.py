"""Fine-grained task status machine (4 states -> 7 states)"""

from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE ai_tasks SET status = 'created' WHERE status = 'pending'")
    op.execute("UPDATE ai_tasks SET status = 'analyzing' WHERE status = 'running'")


def downgrade():
    op.execute(
        "UPDATE ai_tasks SET status = 'pending' "
        "WHERE status IN ('created', 'analyzing', 'generating', 'executing', 'repairing')"
    )
