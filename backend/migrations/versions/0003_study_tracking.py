"""Add structured topics, estimates, and study tracking."""
from alembic import op
import sqlalchemy as sa

revision = "0003_study_tracking"
down_revision = "0002_plan_history"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("activities") as batch:
        batch.alter_column("estimated_hours", existing_type=sa.Float(), nullable=True)
        batch.add_column(sa.Column("topic_details", sa.JSON()))
    with op.batch_alter_table("study_plans") as batch:
        batch.add_column(sa.Column("estimate_source", sa.String(20)))
        batch.add_column(sa.Column("assumptions", sa.JSON()))
        batch.add_column(sa.Column("replaces_plan_id", sa.Integer()))
        batch.add_column(sa.Column("replacement_version", sa.String(64)))
        batch.add_column(sa.Column("proposed_due_date", sa.DateTime(timezone=True)))
        batch.create_foreign_key("fk_study_plan_replacement", "study_plans", ["replaces_plan_id"], ["id"])
    op.add_column("study_sessions", sa.Column("study_status", sa.String(20)))
    op.add_column("study_sessions", sa.Column("effective_minutes", sa.Integer()))
    op.add_column("study_sessions", sa.Column("tracking_history", sa.JSON()))


def downgrade():
    raise RuntimeError("Exporta los datos de seguimiento antes de revertir esta migración.")
