"""Adopt the existing subjects table and add planning tables."""
import sqlalchemy as sa
from alembic import op

revision = "0001_studyflow"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("description", sa.String(500)),
        if_not_exists=True,
    )
    op.create_table(
        "activities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("difficulty", sa.Integer, nullable=False),
        sa.Column("topics", sa.JSON, nullable=False),
        sa.Column("estimated_hours", sa.Float, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name="activity_difficulty"),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="activity_priority"),
        sa.CheckConstraint("estimated_hours > 0", name="activity_hours"),
    )
    op.create_index("ix_activities_subject_id", "activities", ["subject_id"])
    op.create_table(
        "study_plans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("activity_id", sa.Integer, sa.ForeignKey("activities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("availability", sa.JSON, nullable=False),
        sa.Column("busy", sa.JSON, nullable=False),
        sa.Column("max_session_minutes", sa.Integer, nullable=False),
        sa.Column("missing_minutes", sa.Integer, nullable=False),
        sa.Column("reasons", sa.JSON, nullable=False),
        sa.Column("tools_used", sa.JSON, nullable=False),
    )
    op.create_index("ix_study_plans_activity_id", "study_plans", ["activity_id"])
    op.create_index("ix_study_plans_status", "study_plans", ["status"])
    op.create_table(
        "study_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plan_id", sa.Integer, sa.ForeignKey("study_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("objective", sa.String(300), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.CheckConstraint('"end" > start', name="session_end_after_start"),
    )
    op.create_index("ix_study_sessions_plan_id", "study_sessions", ["plan_id"])
    op.create_index("ix_study_sessions_start", "study_sessions", ["start"])


def downgrade():
    op.drop_table("study_sessions")
    op.drop_table("study_plans")
    op.drop_table("activities")
    # The subjects table can predate Alembic and may contain existing data.
