from alembic import context

from app.academic.infrastructure import activities, models
from app.calendar import repository as personal_models
from app.core.database import Base, engine
from app.planning.infrastructure import models as planning_models


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
