
from app.academic.domain.entities import Subject
from app.academic.domain.repositories import SubjectRepository


class SubjectNotFound(Exception):
    pass


class DuplicateSubjectCode(Exception):
    pass


class SubjectService:

    def __init__(self, repository: SubjectRepository):
        self.repository = repository

    def create(self, subject: Subject) -> Subject:
        return self.repository.create(subject)

    def get_all(self) -> list[Subject]:
        return self.repository.get_all()

    def get_by_id(self, subject_id: int) -> Subject:
        subject = self.repository.get_by_id(subject_id)

        if subject is None:
            raise SubjectNotFound("Materia no encontrada")

        return subject

    def update(self, subject: Subject) -> Subject:
        updated = self.repository.update(subject)

        if updated is None:
            raise SubjectNotFound("Materia no encontrada")

        return updated

    def delete(self, subject_id: int) -> None:
        deleted = self.repository.delete(subject_id)

        if not deleted:
            raise SubjectNotFound("Materia no encontrada")


class RelatedRecords(Exception):
    pass
