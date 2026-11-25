
from fastapi import FastAPI

app = FastAPI(
    title="StudyFlow AI API",
    description="API para la planificación académica con IA Agéntica",
    version="0.1.0"
)


@app.get("/")
def root():
    return {
        "application": "StudyFlow AI",
        "message": "API funcionando correctamente",
        "version": "0.1.0"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "studyflow-backend"
    }
