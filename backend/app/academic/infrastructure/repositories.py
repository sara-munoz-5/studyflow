
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.application.services import DuplicateSubjectCode, RelatedRecords
from app.academic.domain.entities import Subject
from app.academic.domain.repositories import SubjectRepository
from app.academic.infrastructure.models import SubjectModel


class SQLAlchemySubjectRepository(SubjectRepository):

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def to_domain(model: SubjectModel) -> Subject:
        return Subject(
            id=model.id,
            name=model.name,
            code=model.code,
            description=model.description,
        )

    def create(self, subject: Subject) -> Subject:
        model = SubjectModel(
            name=subject.name,
            code=subject.code,
            description=subject.description,
        )

        self.db.add(model)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise DuplicateSubjectCode(
                "El código de la materia ya existe"
            )

        self.db.refresh(model)
        return self.to_domain(model)

    def get_all(self) -> list[Subject]:
        statement = select(SubjectModel).order_by(SubjectModel.id)
        models = self.db.scalars(statement).all()
        return [self.to_domain(model) for model in models]

    def get_by_id(self, subject_id: int) -> Subject | None:
        model = self.db.get(SubjectModel, subject_id)
        return self.to_domain(model) if model else None

    def update(self, subject: Subject) -> Subject | None:
        model = self.db.get(SubjectModel, subject.id)

        if model is None:
            return None

        model.name = subject.name
        model.code = subject.code
        model.description = subject.description

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise DuplicateSubjectCode(
                "El código de la materia ya existe"
            )

        self.db.refresh(model)
        return self.to_domain(model)

    def delete(self, subject_id: int) -> bool:
        model = self.db.get(SubjectModel, subject_id)

        if model is None:
            return False

        self.db.delete(model)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise RelatedRecords("La materia tiene actividades asociadas") from exc
        return True
