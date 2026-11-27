
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.academic.domain.entities import Subject
from app.academic.application.services import (
    SubjectService,
    RelatedRecords,
    SubjectNotFound,
    DuplicateSubjectCode,
)
from app.academic.infrastructure.repositories import (
    SQLAlchemySubjectRepository,
)
from app.academic.api.schemas import (
    SubjectCreate,
    SubjectUpdate,
    SubjectResponse,
)


router = APIRouter(prefix="/subjects", tags=["Subjects"])


def get_subject_service(db: Session = Depends(get_db)):
    repository = SQLAlchemySubjectRepository(db)
    return SubjectService(repository)


def handle_error(exc: Exception):
    if isinstance(exc, SubjectNotFound):
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    if isinstance(exc, (DuplicateSubjectCode, RelatedRecords)):
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    raise exc


@router.post(
    "",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subject(
    data: SubjectCreate,
    service: SubjectService = Depends(get_subject_service),
):
    try:
        return service.create(Subject(**data.model_dump()))
    except (SubjectNotFound, DuplicateSubjectCode) as exc:
        handle_error(exc)


@router.get("", response_model=list[SubjectResponse])
def list_subjects(
    service: SubjectService = Depends(get_subject_service),
):
    return service.get_all()


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(
    subject_id: int,
    service: SubjectService = Depends(get_subject_service),
):
    try:
        return service.get_by_id(subject_id)
    except (SubjectNotFound, RelatedRecords) as exc:
        handle_error(exc)


@router.put("/{subject_id}", response_model=SubjectResponse)
def update_subject(
    subject_id: int,
    data: SubjectUpdate,
    service: SubjectService = Depends(get_subject_service),
):
    subject = Subject(id=subject_id, **data.model_dump())

    try:
        return service.update(subject)
    except (SubjectNotFound, DuplicateSubjectCode) as exc:
        handle_error(exc)


@router.delete(
    "/{subject_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_subject(
    subject_id: int,
    service: SubjectService = Depends(get_subject_service),
):
    try:
        service.delete(subject_id)
    except (SubjectNotFound, RelatedRecords) as exc:
        handle_error(exc)
