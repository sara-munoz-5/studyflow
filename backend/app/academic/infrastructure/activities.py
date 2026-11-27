from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.academic.application.services import RelatedRecords, SubjectNotFound
from app.academic.domain.entities import AcademicActivity, ActivityStatus, ActivityType
from app.core.database import Base, lock_planning_calendar
from app.planning.infrastructure.models import PlanModel, SessionModel


class ActivityModel(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="activity_difficulty"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="activity_priority"),
        CheckConstraint("estimated_hours > 0", name="activity_hours"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    type: Mapped[str] = mapped_column(String(20))
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    difficulty: Mapped[int]
    topics: Mapped[list[str]] = mapped_column(JSON)
    estimated_hours: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(20))
    priority: Mapped[int]
    due_day: Mapped[str | None] = mapped_column(String(10))
    topic_weights: Mapped[dict[str, int] | None] = mapped_column(JSON)
    topic_details: Mapped[list[dict] | None] = mapped_column(JSON)


class SQLAlchemyActivityRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def to_domain(row: ActivityModel) -> AcademicActivity:
        return AcademicActivity(
            id=row.id, subject_id=row.subject_id, title=row.title,
            type=ActivityType(row.type),
            due_date=row.due_date.replace(tzinfo=row.due_date.tzinfo or timezone.utc),
            difficulty=row.difficulty, topics=row.topics, estimated_hours=row.estimated_hours,
            status=ActivityStatus(row.status), priority=row.priority, due_day=row.due_day,
            topic_weights=row.topic_weights or {}, topic_details=row.topic_details or [],
        )

    def create(self, activity: AcademicActivity) -> AcademicActivity:
        row = ActivityModel(**asdict(activity))
        self.db.add(row)
        return self._save(row)

    def _save(self, row: ActivityModel) -> AcademicActivity:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if getattr(exc.orig, "sqlstate", None) == "23503":
                raise SubjectNotFound("Materia no encontrada") from exc
            raise
        return self.to_domain(row)

    def get_all(self) -> list[AcademicActivity]:
        return [
            self.to_domain(row)
            for row in self.db.scalars(select(ActivityModel).order_by(ActivityModel.id))
        ]

    def get_by_id(self, activity_id: int) -> AcademicActivity | None:
        row = self.db.get(ActivityModel, activity_id, populate_existing=True)
        return self.to_domain(row) if row else None

    def update(self, activity: AcademicActivity) -> AcademicActivity | None:
        lock_planning_calendar(self.db)
        row = self.db.get(ActivityModel, activity.id, populate_existing=True)
        if row is None:
            return None
        affected_session = (
            select(SessionModel.id).join(PlanModel).where(
                PlanModel.activity_id == activity.id, PlanModel.status == "approved",
                SessionModel.end > datetime.now(timezone.utc),
                (SessionModel.end > activity.due_date) | SessionModel.topic.not_in(activity.topics),
            ).limit(1)
        )
        if self.db.scalar(affected_session) is not None:
            raise RelatedRecords("El cambio de plazo o temas invalidaría sesiones aprobadas")
        changes = asdict(activity)
        del changes["id"]
        for name, value in changes.items():
            setattr(row, name, value)
        return self._save(row)

    def delete(self, activity_id: int) -> bool:
        row = self.db.get(ActivityModel, activity_id, populate_existing=True)
        if row is None:
            return False
        self.db.delete(row)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise RelatedRecords("La actividad tiene planes asociados") from exc
        return True
