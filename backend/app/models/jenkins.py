from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


# Phase 2 reserved: Jenkins build data integration
class JenkinsBuild(Base):
    __tablename__ = "jenkins_builds"

    id = Column(Integer, primary_key=True)
    job_name = Column(String(200), nullable=False)
    build_number = Column(Integer, nullable=False)
    status = Column(String(20))     # SUCCESS/FAILURE/ABORTED/IN_PROGRESS
    duration_ms = Column(Integer)
    repo_url = Column(String(500))
    triggered_by = Column(String(100))
    build_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
