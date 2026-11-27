from datetime import datetime, timezone
from typing import Protocol

from icalendar import Calendar, Event

from app.planning.domain.entities import StudyPlan


class CalendarExporter(Protocol):
    def export(self, plan: StudyPlan, activity_title: str, subject_name: str | None = None) -> bytes: ...


class CalendarPublisher(Protocol):
    """Contract for future authenticated calendar adapters."""

    def publish(self, plan: StudyPlan, activity_title: str) -> list[str]: ...


class GoogleCalendarPublisher(CalendarPublisher, Protocol):
    pass


class OutlookCalendarPublisher(CalendarPublisher, Protocol):
    pass


class ICalendarExporter:
    def export(self, plan: StudyPlan, activity_title: str, subject_name: str | None = None) -> bytes:
        calendar = Calendar()
        calendar.add("prodid", "-//StudyFlow AI//Study plans//ES")
        calendar.add("version", "2.0")
        calendar.add("calscale", "GREGORIAN")
        calendar.add("X-WR-TIMEZONE", plan.timezone)

        timestamp = datetime.now(timezone.utc)
        for session in plan.sessions:
            event = Event()
            event.add("uid", f"plan-{plan.id}-session-{session.id}@studyflow.local")
            event.add("dtstamp", timestamp)
            event.add("dtstart", session.start.astimezone(timezone.utc))
            event.add("dtend", session.end.astimezone(timezone.utc))
            title = f"{activity_title}: {session.topic}"
            event.add("summary", f"{title} · {subject_name}" if subject_name else title)
            event.add("description", session.objective)
            if subject_name:
                event.add("categories", [subject_name])
                event.add("X-STUDYFLOW-SUBJECT", subject_name)
            event.add("status", "CONFIRMED")
            calendar.add_component(event)
        return calendar.to_ical()
