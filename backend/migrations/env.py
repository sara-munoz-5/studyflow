from alembic import context

# Import ORM modules so their tables are registered in Base.metadata.
from app.academic.infrastructure import activities, models  # noqa: F401
from app.calendar import repository as personal_models  # noqa: F401
from app.core.database import Base, engine
from app.planning.infrastructure import models as planning_models  # noqa: F401


def migrate_offline():
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def migrate_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    migrate_offline()
else:
    migrate_online()
