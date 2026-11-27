from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.academic.infrastructure.models import SubjectModel as SubjectModel
from app.core.database import Base


class PlanModel(Base):
    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="RESTRICT"), index=True)
    timezone: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    availability: Mapped[list[dict]] = mapped_column(JSON)
    busy: Mapped[list[dict]] = mapped_column(JSON)
    max_session_minutes: Mapped[int]
    missing_minutes: Mapped[int]
    reasons: Mapped[list[str]] = mapped_column(JSON)
    tools_used: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage: Mapped[list[dict] | None] = mapped_column(JSON)
    estimate_source: Mapped[str | None] = mapped_column(String(20))
    assumptions: Mapped[list[str] | None] = mapped_column(JSON)
    replaces_plan_id: Mapped[int | None] = mapped_column(ForeignKey("study_plans.id"))
    replacement_version: Mapped[str | None] = mapped_column(String(64))
    proposed_due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    derived_from_plan_id: Mapped[int | None] = mapped_column(ForeignKey("study_plans.id"))
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True, index=True)
    request_signature: Mapped[str | None] = mapped_column(String(64))


class SessionModel(Base):
    __tablename__ = "study_sessions"
    __table_args__ = (CheckConstraint('"end" > start', name="session_end_after_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(120))
    objective: Mapped[str] = mapped_column(String(300))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    study_status: Mapped[str | None] = mapped_column(String(20))
    effective_minutes: Mapped[int | None]
    tracking_history: Mapped[list[dict] | None] = mapped_column(JSON)
