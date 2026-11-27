from dataclasses import asdict
from datetime import date, time

from sqlalchemy import JSON, Date, String, Time, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base

from .domain import PersonalBlock


class PersonalBlockModel(Base):
    __tablename__ = "personal_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    day: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    category: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(String(500))
    weekdays: Mapped[list[int]] = mapped_column(JSON)
    until: Mapped[date | None] = mapped_column(Date)


class SQLAlchemyPersonalRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def to_domain(row: PersonalBlockModel) -> PersonalBlock:
        return PersonalBlock(
            id=row.id, title=row.title, day=row.day, start_time=row.start_time, end_time=row.end_time,
            category=row.category, description=row.description, weekdays=row.weekdays, until=row.until,
        )

    def list_all(self) -> list[PersonalBlock]:
        return [self.to_domain(row) for row in self.db.scalars(
            select(PersonalBlockModel).order_by(PersonalBlockModel.day, PersonalBlockModel.start_time, PersonalBlockModel.id)
        )]

    def get(self, block_id: int) -> PersonalBlock | None:
        row = self.db.get(PersonalBlockModel, block_id, populate_existing=True)
        return self.to_domain(row) if row else None

    def save(self, block: PersonalBlock) -> PersonalBlock:
        data = asdict(block)
        del data["id"]
        if block.id is None:
            row = PersonalBlockModel(**data)
            self.db.add(row)
        else:
            row = self.db.get(PersonalBlockModel, block.id, populate_existing=True)
            for name, value in data.items():
                setattr(row, name, value)
        self.db.commit()
        return self.to_domain(row)

    def delete(self, block_id: int) -> bool:
        row = self.db.get(PersonalBlockModel, block_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True
