
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db


app = FastAPI(
    title="StudyFlow AI API",
    description="API para planificación académica con IA Agéntica",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "application": "StudyFlow AI",
        "message": "API funcionando correctamente",
        "version": "0.1.0",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "studyflow-backend",
    }


@app.get("/health/db")
def database_health(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT 1")).scalar()

    return {
        "status": "healthy" if result == 1 else "unhealthy",
        "database": "postgresql",
        "connection": "successful" if result == 1 else "failed",
    }
