
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# URL de conexión configurada mediante Docker Compose
DATABASE_URL = os.environ["DATABASE_URL"]


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
