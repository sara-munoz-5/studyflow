from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from app.academic.domain.entities import Subject as Subject
from app.academic.domain.entities import topic_id


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class StudySession:
    topic: str
    objective: str
    start: datetime
    end: datetime
    status: str = "proposed"
    id: int | None = None
    study_status: str = "pending"
    effective_minutes: int = 0
    tracking_history: list[dict] = field(default_factory=list)

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class TopicCoverage:
    topic_id: str
    topic: str
    required_minutes: int | None
    planned_minutes: int
    objective: str | None = None
    suggested_minutes: int | None = None
    rationale: str | None = None
    priority: int | None = None

    @property
    def status(self) -> str:
        if self.required_minutes == 0:
            return "scheduled"
        if not self.planned_minutes:
            return "pending"
        if self.required_minutes is None:
            return "historical"
        return "scheduled" if self.planned_minutes >= self.required_minutes else "partial"


@dataclass
class StudyPlan:
    activity_id: int
    timezone: str
    mode: str
    availability: list[Window]
    busy: list[Window]
    max_session_minutes: int
    sessions: list[StudySession]
    missing_minutes: int
    reasons: list[str]
    status: str = "draft"
    tools_used: list[str] = field(default_factory=list)
    id: int | None = None
    created_at: datetime | None = None
    coverage: list[TopicCoverage] = field(default_factory=list)
    estimate_source: str = "legacy"
    assumptions: list[str] = field(default_factory=list)
    replaces_plan_id: int | None = None
    replacement_version: str | None = None
    proposed_due_date: datetime | None = None

    @property
    def completed_minutes(self) -> int:
        return sum(session.effective_minutes for session in self.sessions)

    @property
    def planned_minutes(self) -> int:
        return sum(session.duration_minutes for session in self.sessions)

    @property
    def required_minutes(self) -> int:
        return self.planned_minutes + self.missing_minutes

    def restore_legacy_coverage(self, topics: list[str]) -> None:
        if self.coverage:
            return
        totals = Counter()
        objectives = {}
        for session in self.sessions:
            totals[session.topic] += session.duration_minutes
            objectives[session.topic] = session.objective
        self.coverage = [TopicCoverage(topic_id(self.activity_id, topic), topic, None, totals[topic],
                                      objectives.get(topic)) for topic in dict.fromkeys([*topics, *totals])]
