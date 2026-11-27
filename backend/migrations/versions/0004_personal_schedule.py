"""Add recurring personal blocks and generation identity."""
from alembic import op
import sqlalchemy as sa

revision = "0004_personal_schedule"
down_revision = "0003_study_tracking"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("category", sa.String(50)),
        sa.Column("description", sa.String(500)),
        sa.Column("weekdays", sa.JSON(), nullable=False),
        sa.Column("until", sa.Date()),
    )
    with op.batch_alter_table("study_plans") as batch:
        batch.add_column(sa.Column("derived_from_plan_id", sa.Integer()))
        batch.add_column(sa.Column("request_id", sa.String(36)))
        batch.add_column(sa.Column("request_signature", sa.String(64)))
        batch.create_foreign_key("fk_study_plan_generation", "study_plans", ["derived_from_plan_id"], ["id"])
        batch.create_index("ix_study_plans_request_id", ["request_id"], unique=True)


def downgrade():
    raise RuntimeError("La revisión conserva compromisos personales y relaciones de historial.")
