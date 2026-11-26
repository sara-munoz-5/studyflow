from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from threading import Lock

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import lock_planning_calendar
from app.planning.application.services import PlanConflict
from app.planning.domain.entities import StudyPlan, StudySession, TopicCoverage, Window

from .models import PlanModel, SessionModel

# PostgreSQL serializes approvals across processes. The local lock supports SQLite tests.
sqlite_approval_lock = Lock()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def encode(windows: list[Window]) -> list[dict]:
    return [{"start": window.start.isoformat(), "end": window.end.isoformat()} for window in windows]


def decode(windows: list[dict]) -> list[Window]:
    return [Window(datetime.fromisoformat(item["start"]), datetime.fromisoformat(item["end"])) for item in windows]


class SQLAlchemyPlanRepository:
    def __init__(self, db: Session):
        self.db = db

    @contextmanager
    def serialized(self):
        if self.db.get_bind().dialect.name == "postgresql":
            lock_planning_calendar(self.db)
            yield
        else:
            with sqlite_approval_lock:
                yield

    def _to_domain(self, row: PlanModel) -> StudyPlan:
        sessions = self.db.scalars(
            select(SessionModel).where(SessionModel.plan_id == row.id).order_by(SessionModel.start)
        )
        return StudyPlan(
            id=row.id, activity_id=row.activity_id, timezone=row.timezone, mode=row.mode,
            availability=decode(row.availability), busy=decode(row.busy),
            status=row.status, max_session_minutes=row.max_session_minutes,
            missing_minutes=row.missing_minutes, reasons=row.reasons, tools_used=row.tools_used,
            created_at=utc(row.created_at) if row.created_at else None,
            estimate_source=row.estimate_source or "legacy", assumptions=row.assumptions or [],
            replaces_plan_id=row.replaces_plan_id, replacement_version=row.replacement_version,
            proposed_due_date=utc(row.proposed_due_date) if row.proposed_due_date else None,
            coverage=[TopicCoverage(**item) for item in (row.coverage or [])],
            sessions=[
                StudySession(item.topic, item.objective, utc(item.start), utc(item.end), item.status, item.id,
                             item.study_status or "pending", item.effective_minutes or 0, item.tracking_history or [])
                for item in sessions
            ],
        )

    def save(self, plan: StudyPlan) -> StudyPlan:
        row = PlanModel(
            activity_id=plan.activity_id, timezone=plan.timezone, mode=plan.mode, status=plan.status,
            availability=encode(plan.availability), busy=encode(plan.busy),
            max_session_minutes=plan.max_session_minutes, missing_minutes=plan.missing_minutes,
            reasons=plan.reasons, tools_used=plan.tools_used, created_at=plan.created_at,
            coverage=[asdict(item) for item in plan.coverage], estimate_source=plan.estimate_source,
            assumptions=plan.assumptions, replaces_plan_id=plan.replaces_plan_id,
            replacement_version=plan.replacement_version, proposed_due_date=plan.proposed_due_date,
        )
        self.db.add(row)
        try:
            self.db.flush()
            self.db.add_all([
                SessionModel(plan_id=row.id, topic=item.topic, objective=item.objective,
                             start=item.start, end=item.end, status=item.status)
                for item in plan.sessions
            ])
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if getattr(exc.orig, "sqlstate", None) == "23503":
                raise PlanConflict("La actividad cambió durante la generación") from exc
            raise
        return self._to_domain(row)

    def get(self, plan_id: int) -> StudyPlan | None:
        row = self.db.get(PlanModel, plan_id, populate_existing=True)
        return self._to_domain(row) if row else None

    def list_all(self) -> list[StudyPlan]:
        return [self._to_domain(row) for row in self.db.scalars(select(PlanModel).order_by(PlanModel.id.desc()))]

    def busy(self, since: datetime, exclude_plan_id: int | None = None) -> list[Window]:
        statement = (
            select(SessionModel.start, SessionModel.end)
            .join(PlanModel, SessionModel.plan_id == PlanModel.id)
            .where(SessionModel.end > since,
                   (PlanModel.status == "approved") |
                   ((PlanModel.status == "superseded") & (SessionModel.study_status == "completed")))
        )
        if exclude_plan_id is not None:
            statement = statement.where(
                (PlanModel.id != exclude_plan_id) | (SessionModel.study_status == "completed")
            )
        return [Window(utc(start), utc(end)) for start, end in self.db.execute(statement)]

    def track(self, session_id: int, status: str, minutes: int, now: datetime) -> None:
        row = self.db.get(SessionModel, session_id, populate_existing=True)
        before = {"status": row.study_status or "pending", "minutes": row.effective_minutes or 0}
        after = {"status": status, "minutes": minutes}
        if before == after:
            return
        row.tracking_history = [*(row.tracking_history or []),
                                {"at": now.isoformat(), "before": before, "after": after}]
        row.study_status = status
        row.effective_minutes = minutes
        self.db.commit()

    def approve(self, plan: StudyPlan, now: datetime) -> StudyPlan:
        if plan.replaces_plan_id:
            previous = self.db.get(PlanModel, plan.replaces_plan_id)
            previous.status = "superseded"
            self.db.execute(
                update(SessionModel).where(
                    SessionModel.plan_id == previous.id, SessionModel.end > now,
                    (SessionModel.study_status.is_(None) | (SessionModel.study_status != "completed")),
                ).values(status="replaced")
            )
        if plan.proposed_due_date:
            from app.academic.infrastructure.activities import ActivityModel
            activity = self.db.get(ActivityModel, plan.activity_id)
            activity.due_date = plan.proposed_due_date
            activity.due_day = None
        row = self.db.get(PlanModel, plan.id)
        row.status = "approved"
        self.db.execute(
            update(SessionModel).where(SessionModel.plan_id == plan.id).values(status="scheduled")
        )
        self.db.commit()
        return self._to_domain(row)
