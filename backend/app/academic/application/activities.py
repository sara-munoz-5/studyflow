from app.academic.domain.entities import AcademicActivity
from app.academic.domain.repositories import ActivityRepository, SubjectRepository

from .services import SubjectNotFound


class ActivityNotFound(Exception):
    pass


class ActivityService:
    def __init__(self, repository: ActivityRepository, subjects: SubjectRepository):
        self.repository = repository
        self.subjects = subjects

    def get_all(self) -> list[AcademicActivity]:
        return self.repository.get_all()

    def get_by_id(self, activity_id: int) -> AcademicActivity:
        activity = self.repository.get_by_id(activity_id)
        if activity is None:
            raise ActivityNotFound("Actividad no encontrada")
        return activity

    def save(self, activity: AcademicActivity) -> AcademicActivity:
        if self.subjects.get_by_id(activity.subject_id) is None:
            raise SubjectNotFound("Materia no encontrada")
        if activity.id is None:
            return self.repository.create(activity)
        updated = self.repository.update(activity)
        if updated is None:
            raise ActivityNotFound("Actividad no encontrada")
        return updated

    def delete(self, activity_id: int) -> None:
        if not self.repository.delete(activity_id):
            raise ActivityNotFound("Actividad no encontrada")
