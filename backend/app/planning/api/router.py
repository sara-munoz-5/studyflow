from datetime import timezone
from uuid import UUID
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.academic.api.activities import get_activity_service
from app.agents.workflow import run_agent
from app.calendar.providers import CalendarExporter, ICalendarExporter
from app.core.database import get_db
from app.planning.application.services import PlanService
from app.planning.domain.entities import Window
from app.planning.infrastructure.repositories import SQLAlchemyPlanRepository

from .progress import plan_progress

router = APIRouter(prefix="/plans", tags=["Plans"])


class WindowInput(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def chronological(self):
        if self.start >= self.end:
            raise ValueError("La hora de fin debe ser posterior al inicio")
        return self

    def to_domain(self):
        return Window(self.start.astimezone(timezone.utc), self.end.astimezone(timezone.utc))


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_id: int = Field(gt=0)
    timezone: str = Field(default="America/Bogota", max_length=100)
    availability: list[WindowInput] = Field(min_length=1, max_length=100)
    busy: list[WindowInput] = Field(default_factory=list, max_length=200)
    max_session_minutes: int = Field(default=60, ge=15, le=120)
    mode: Literal["agent", "deterministic"] = "agent"
    target_minutes: int | None = Field(default=None, ge=1, le=12000)
    replaces_plan_id: int | None = Field(default=None, gt=0)
    proposed_due_date: AwareDatetime | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Indica una zona horaria IANA válida") from exc
        return value


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None
    topic: str
    objective: str
    start: AwareDatetime
    end: AwareDatetime
    duration_minutes: int
    status: str
    study_status: str
    effective_minutes: int
    tracking_history: list[dict]


class CoverageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    topic_id: str
    topic: str
    required_minutes: int | None
    planned_minutes: int
    status: str
    objective: str | None
    suggested_minutes: int | None
    rationale: str | None
    priority: int | None


class SessionTrackingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "completed", "partial", "not_done"]
    effective_minutes: int | None = Field(default=None, ge=0)


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None
    activity_id: int
    timezone: str
    mode: str
    status: str
    sessions: list[SessionResponse]
    missing_minutes: int
    reasons: list[str]
    tools_used: list[str]
    created_at: AwareDatetime | None
    availability: list[WindowInput]
    busy: list[WindowInput]
    max_session_minutes: int
    planned_minutes: int
    required_minutes: int
    completed_minutes: int
    estimate_source: str
    assumptions: list[str]
    replaces_plan_id: int | None
    proposed_due_date: AwareDatetime | None
    coverage: list[CoverageResponse]


def get_service(db: Session = Depends(get_db)) -> PlanService:
    return PlanService(SQLAlchemyPlanRepository(db), get_activity_service(db))


def get_exporter() -> CalendarExporter:
    return ICalendarExporter()


Service = Annotated[PlanService, Depends(get_service)]


@router.post("", response_model=PlanResponse, status_code=201)
def generate(data: PlanInput, service: Service, response: Response,
             progress_id: Annotated[UUID | None, Header(alias="X-Plan-Progress")] = None):
    with plan_progress.track(progress_id) as observer:
        plan = service.generate(
            data.activity_id, data.timezone, [item.to_domain() for item in data.availability],
            [item.to_domain() for item in data.busy], data.max_session_minutes, data.mode, run_agent, observer,
            data.target_minutes, data.replaces_plan_id,
            data.proposed_due_date.astimezone(timezone.utc) if data.proposed_due_date else None,
        )
    if plan.status == "unavailable":
        response.status_code = 200
    return plan


@router.get("", response_model=list[PlanResponse])
def list_plans(service: Service):
    return service.list_all()


@router.get("/progress/{progress_id}")
def get_progress(progress_id: UUID):
    return {"events": plan_progress.events(progress_id)}


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: int, service: Service):
    return service.get(plan_id)


@router.post("/{plan_id}/approve", response_model=PlanResponse)
def approve(plan_id: int, service: Service):
    return service.approve(plan_id)


@router.patch("/{plan_id}/sessions/{session_id}/tracking", response_model=PlanResponse)
def track_session(plan_id: int, session_id: int, data: SessionTrackingInput, service: Service):
    return service.track(plan_id, session_id, data.status, data.effective_minutes)


@router.get("/{plan_id}/calendar.ics")
def export(plan_id: int, service: Service, exporter: Annotated[CalendarExporter, Depends(get_exporter)]):
    plan = service.get(plan_id)
    if plan.status != "approved":
        raise HTTPException(409, "Aprueba el plan antes de exportarlo")
    activity = service.activities.get_by_id(plan.activity_id)
    subject = service.activities.subjects.get_by_id(activity.subject_id)
    return Response(
        exporter.export(plan, activity.title, subject.name if subject else None), media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="studyflow-{plan_id}.ics"'},
    )
