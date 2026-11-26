
import os

from sqlalchemy import URL, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# URL de conexión configurada mediante Docker Compose
DATABASE_URL = os.getenv("DATABASE_URL") or URL.create(
    "postgresql+psycopg",
    username=os.getenv("POSTGRES_USER", "studyflow"),
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST", "db"),
    database=os.getenv("POSTGRES_DB", "studyflow_db"),
)


# Motor de conexión con PostgreSQL
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


# Fábrica de sesiones
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


# Clase base para los futuros modelos ORM
class Base(DeclarativeBase):
    pass


# Dependencia para obtener una sesión de base de datos
def get_db():
    with SessionLocal() as db:
        yield db


def lock_planning_calendar(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(87641031)"))
