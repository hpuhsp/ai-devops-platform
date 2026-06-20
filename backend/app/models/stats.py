from sqlalchemy import Column, Integer, String, Date, Numeric, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class StatsSnapshot(Base):
    __tablename__ = "stats_snapshots"
    __table_args__ = (
        UniqueConstraint("date", "metric_type", "dimensions", name="uq_stats_snapshot"),
    )

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    metric_type = Column(String(50), nullable=False)  # ai_review_count/test_gen_count/block_count/token_cost
    value = Column(Numeric, nullable=False)
    dimensions = Column(JSONB, default={})            # {repo_id: 1, task_type: "code_review"}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
