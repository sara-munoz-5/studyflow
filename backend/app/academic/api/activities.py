from uuid import UUID, uuid4
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from sqlalchemy.orm import Session

from app.academic.application.activities import ActivityService
from app.academic.domain.entities import AcademicActivity, ActivityStatus, ActivityType
from app.academic.infrastructure.activities import SQLAlchemyActivityRepository
from app.academic.infrastructure.repositories import SQLAlchemySubjectRepository
from app.core.database import get_db

router = APIRouter(prefix="/activities", tags=["Activities"])
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class TopicDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None
    name: Topic
    priority: int = Field(default=3, ge=1, le=5)
    mastery: int | None = Field(default=None, ge=1, le=5)


class ActivityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    subject_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=150)
    type: ActivityType
    due_date: AwareDatetime | None = None
    difficulty: int = Field(ge=1, le=5)
    topics: list[Topic] = Field(default_factory=list)
    topic_details: list[TopicDetail] = Field(default_factory=list)
    estimated_hours: float | None = Field(default=None, gt=0, le=200)
    status: ActivityStatus = ActivityStatus.PENDING
    priority: int = Field(default=3, ge=1, le=5)
    due_day: date | None = None
    topic_weights: dict[str, Annotated[int, Field(ge=1, le=5)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def date_only_deadline(self):
        if self.topic_details:
            names = self.unique_topics([item.name for item in self.topic_details])
            if self.topics and names != self.topics:
                raise ValueError("Los nombres de ambas listas de temas deben coincidir")
            self.topics = names
            ids = [item.id for item in self.topic_details if item.id]
            if len(ids) != len(set(ids)):
                raise ValueError("Los identificadores de tema deben ser distintos")
        if not self.topics:
            raise ValueError("Agrega al menos un tema")
        if not self.topic_weights.keys() <= set(self.topics):
            raise ValueError("El esfuerzo debe corresponder a temas de la actividad")
        if self.due_date is None and self.due_day is None:
            raise ValueError("Indica una fecha límite")
        if self.due_day is not None:
            if self.due_day == date.max:
                raise ValueError("La fecha límite excede el rango disponible")
            self.due_date = datetime.combine(self.due_day + timedelta(days=1), time.min,
                                             ZoneInfo("America/Bogota")).astimezone(timezone.utc)
        return self

    @field_validator("topics")
    @classmethod
    def unique_topics(cls, topics: list[str]) -> list[str]:
        if len({topic.casefold() for topic in topics}) != len(topics):
            raise ValueError("Los temas deben ser distintos")
        return topics

    @field_validator("due_date")
    @classmethod
    def utc_deadline(cls, value):
        return value.astimezone(timezone.utc) if value is not None else None


class ActivityResponse(ActivityInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    topic_ids: dict[str, str]
    topic_details: list[TopicDetail] = Field(validation_alias="structured_topics")
    due_date: AwareDatetime


def get_activity_service(db: Session = Depends(get_db)) -> ActivityService:
    return ActivityService(SQLAlchemyActivityRepository(db), SQLAlchemySubjectRepository(db))


Service = Annotated[ActivityService, Depends(get_activity_service)]


def activity_from_input(data: ActivityInput, previous: AcademicActivity | None = None) -> AcademicActivity:
    existing = {item["name"]: item for item in previous.structured_topics} if previous else {}
    allowed_ids = {item["id"] for item in existing.values()}
    details = []
    for item in data.topic_details:
        identifier = str(item.id) if item.id else None
        if identifier and identifier not in allowed_ids:
            raise HTTPException(422, "El identificador no pertenece a esta actividad")
        record = item.model_dump(mode="json")
        record["id"] = identifier or existing.get(item.name, {}).get("id") or str(uuid4())
        details.append(record)
    if not data.topic_details:
        details = [existing[name] for name in data.topics if name in existing]
    if len({item["id"] for item in details}) != len(details):
        raise HTTPException(422, "Los identificadores de tema deben ser distintos")
    return AcademicActivity(id=previous.id if previous else None,
                            **data.model_dump(exclude={"due_day", "topic_details"}),
                            due_day=data.due_day.isoformat() if data.due_day else None,
                            topic_details=details)


@router.post("", response_model=ActivityResponse, status_code=201)
def create_activity(data: ActivityInput, service: Service):
    return service.save(activity_from_input(data))


@router.get("", response_model=list[ActivityResponse])
def list_activities(service: Service):
    return service.get_all()


@router.get("/{activity_id}", response_model=ActivityResponse)
def get_activity(activity_id: int, service: Service):
    return service.get_by_id(activity_id)


@router.put("/{activity_id}", response_model=ActivityResponse)
def update_activity(activity_id: int, data: ActivityInput, service: Service):
    return service.save(activity_from_input(data, service.get_by_id(activity_id)))


@router.delete("/{activity_id}", status_code=204)
def delete_activity(activity_id: int, service: Service):
    service.delete(activity_id)
