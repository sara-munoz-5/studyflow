from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5


@dataclass
class Subject:
    name: str
    code: str
    description: str | None = None
    id: int | None = None


class ActivityType(StrEnum):
    EXAM = "exam"
    LABORATORY = "laboratory"
    ASSIGNMENT = "assignment"
    PROJECT = "project"


class ActivityStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class AcademicActivity:
    subject_id: int
    title: str
    type: ActivityType
    due_date: datetime
    difficulty: int
    topics: list[str]
    estimated_hours: float | None
    status: ActivityStatus
    priority: int = 3
    id: int | None = None
    due_day: str | None = None
    topic_weights: dict[str, int] = field(default_factory=dict)
    topic_details: list[dict] = field(default_factory=list)

    @property
    def topic_ids(self) -> dict[str, str]:
        return {item['name']: item['id'] for item in self.structured_topics}

    @property
    def structured_topics(self) -> list[dict]:
        saved = {item['name']: item for item in self.topic_details}
        return [saved.get(topic, {'id': topic_id(self.id, topic), 'name': topic,
                                  'priority': 3, 'mastery': None})
                for topic in self.topics]


def topic_id(activity_id: int | None, topic: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"studyflow:activity:{activity_id}:topic:{topic}"))
