from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.planning.infrastructure.repositories import SQLAlchemyPlanRepository

from .application import PersonalSchedule
from .domain import BOGOTA, PersonalBlock, occurrences
from .repository import SQLAlchemyPersonalRepository

router = APIRouter(prefix="/personal-blocks", tags=["Personal schedule"])


class BlockInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=150)
    day: date
    start_time: time
    end_time: time
    category: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(default_factory=list, max_length=7)
    until: date | None = None

    @model_validator(mode="after")
    def valid_schedule(self):
        if self.start_time.tzinfo or self.end_time.tzinfo or self.end_time <= self.start_time:
            raise ValueError("Indica horas de Bogotá con fin posterior al inicio")
        if self.until and (not self.weekdays or self.until < self.day):
            raise ValueError("La fecha final requiere repetición y debe ser posterior o igual al inicio")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("Cada día de repetición se selecciona una vez")
        return self


class BlockResponse(BlockInput):
    model_config = ConfigDict(from_attributes=True)
    id: int


class OccurrenceResponse(BaseModel):
    block_id: int
    title: str
    start: datetime
    end: datetime
    category: str | None
    description: str | None


def get_schedule(db: Session = Depends(get_db)) -> PersonalSchedule:
    return PersonalSchedule(SQLAlchemyPersonalRepository(db), SQLAlchemyPlanRepository(db))


Schedule = Annotated[PersonalSchedule, Depends(get_schedule)]


@router.get("", response_model=list[BlockResponse])
def list_blocks(schedule: Schedule):
    return schedule.repository.list_all()


@router.post("", response_model=BlockResponse, status_code=201)
def create_block(data: BlockInput, schedule: Schedule):
    return schedule.save(PersonalBlock(**data.model_dump()))


@router.get("/occurrences", response_model=list[OccurrenceResponse])
def list_occurrences(start: date, end: date, schedule: Schedule):
    if not timedelta(0) < end - start <= timedelta(days=366):
        raise HTTPException(422, "Consulta un intervalo de hasta 366 días con fin exclusivo")
    lower, upper = (datetime.combine(day, time.min, BOGOTA) for day in (start, end))
    return sorted((
        OccurrenceResponse(block_id=block.id, title=block.title, start=item.start, end=item.end,
                           category=block.category, description=block.description)
        for block in schedule.repository.list_all() for item in occurrences(block, lower, upper)
    ), key=lambda item: (item.start, item.block_id))


@router.get("/{block_id}", response_model=BlockResponse)
def get_block(block_id: int, schedule: Schedule):
    return schedule.get(block_id)


@router.put("/{block_id}", response_model=BlockResponse)
def update_block(block_id: int, data: BlockInput, schedule: Schedule):
    return schedule.save(PersonalBlock(id=block_id, **data.model_dump()))


@router.delete("/{block_id}", status_code=204)
def delete_block(block_id: int, schedule: Schedule):
    schedule.delete(block_id)
