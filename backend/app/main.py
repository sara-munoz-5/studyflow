from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.academic.api.activities import router as activity_router
from app.academic.api.router import router as subject_router
from app.academic.application.activities import ActivityNotFound
from app.academic.application.services import RelatedRecords, SubjectNotFound
from app.agents.workflow import AgentFailure, AgentUnavailable
from app.core.database import get_db
from app.planning.api.router import router as plan_router
from app.planning.application.services import PlanConflict, PlanNotFound

app = FastAPI(
    title="StudyFlow AI API",
    description="API para planificación académica con IA Agéntica",
    version="0.1.0",
)

app.include_router(subject_router)
app.include_router(activity_router)
app.include_router(plan_router)

ERROR_STATUS = {
    ActivityNotFound: 404, SubjectNotFound: 404, PlanNotFound: 404,
    RelatedRecords: 409, PlanConflict: 409, AgentUnavailable: 503, AgentFailure: 502,
}


def application_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=ERROR_STATUS[type(exc)], content={"detail": str(exc)})


for error in ERROR_STATUS:
    app.add_exception_handler(error, application_error)


@app.get("/")
def root():
    return {
        "application": "StudyFlow AI",
        "message": "API funcionando correctamente",
        "version": "0.1.0",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "studyflow-backend"}


@app.get("/health/db")
def database_health(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT 1")).scalar()
    return {
        "status": "healthy" if result == 1 else "unhealthy",
        "database": "postgresql",
        "connection": "successful" if result == 1 else "failed",
    }
