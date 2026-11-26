"""Preserve plan coverage and optional day-only deadlines."""
from alembic import op
import sqlalchemy as sa

revision = "0002_plan_history"
down_revision = "0001_studyflow"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activities", sa.Column("due_day", sa.String(10)))
    op.add_column("activities", sa.Column("topic_weights", sa.JSON()))
    op.add_column("study_plans", sa.Column("created_at", sa.DateTime(timezone=True)))
    op.add_column("study_plans", sa.Column("coverage", sa.JSON()))


def downgrade():
    op.drop_column("study_plans", "coverage")
    op.drop_column("study_plans", "created_at")
    op.drop_column("activities", "topic_weights")
    op.drop_column("activities", "due_day")
