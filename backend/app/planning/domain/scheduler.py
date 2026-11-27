from datetime import datetime, timedelta
from math import ceil

from app.academic.domain.entities import AcademicActivity

from .entities import StudySession, Window

MINUTE = timedelta(minutes=1)


def merge(windows: list[Window]) -> list[Window]:
    merged: list[Window] = []
    for window in sorted(windows, key=lambda item: item.start):
        if merged and window.start <= merged[-1].end:
            merged[-1] = Window(merged[-1].start, max(window.end, merged[-1].end))
        else:
            merged.append(window)
    return merged


def free_slots(
    availability: list[Window], busy: list[Window], now: datetime, deadline: datetime,
) -> list[Window]:
    free = []
    occupied = merge(busy)
    for window in merge(availability):
        cursor = max(now, window.start)
        end = min(deadline, window.end)
        if end <= cursor:
            continue
        for block in occupied:
            if block.end <= cursor:
                continue
            if block.start >= end:
                break
            if block.start - cursor >= MINUTE:
                free.append(Window(cursor, block.start))
            cursor = max(cursor, block.end)
        if end - cursor >= MINUTE:
            free.append(Window(cursor, end))
    return free


def effort(activity: AcademicActivity) -> int:
    if activity.estimated_hours is not None:
        return max(len(activity.topics), ceil(activity.estimated_hours * 60))
    return sum(rough_effort(activity).values())


def rough_effort(activity: AcademicActivity) -> dict[str, int]:
    return {item['name']: 10 + 5 * activity.difficulty + 5 * (5 - (item['mastery'] or 3))
            for item in activity.structured_topics}


def topic_quotas(activity: AcademicActivity, objectives: dict[str, str],
                 weights: dict[str, int] | None = None, total_minutes: int | None = None) -> dict[str, int]:
    # Give every topic a baseline minute, then distribute the remaining effort proportionally.
    topics = list(objectives)
    weights = weights or {}
    weights = {topic: activity.topic_weights.get(topic, weights.get(topic, 1)) for topic in topics}
    total = total_minutes if total_minutes is not None else effort(activity)
    remaining = total - len(topics)
    denominator = sum(weights[topic] for topic in topics)
    shares = {topic: divmod(remaining * weights[topic], denominator) for topic in topics}
    quotas = {topic: 1 + share[0] for topic, share in shares.items()}
    remainder = total - sum(quotas.values())
    for topic in sorted(topics, key=lambda item: shares[item][1], reverse=True)[:remainder]:
        quotas[topic] += 1
    return quotas


def allocate(
    activity: AcademicActivity, slots: list[Window], max_minutes: int,
    objectives: dict[str, str], weights: dict[str, int] | None = None,
    quotas: dict[str, int] | None = None,
) -> list[StudySession]:
    remaining = dict(quotas if quotas is not None else topic_quotas(activity, objectives, weights))
    remaining = {topic: minutes for topic, minutes in remaining.items() if minutes > 0}
    total = sum(remaining.values())
    # Difficult topics get shorter blocks. Higher priority consumes earlier slots first.
    limit = min(max_minutes, 75 - 10 * activity.difficulty)
    targets = [slot for slot in slots if slot.end - slot.start >= MINUTE]
    if targets and activity.priority <= 2:
        # Lower priority starts later on the first day when there is enough spare time.
        first = targets[0]
        spare = sum(int((slot.end - slot.start) // MINUTE) for slot in targets) - total
        delay = min(30, max(0, spare), int((first.end - first.start) // MINUTE) - 1)
        targets[0] = Window(first.start + delay * MINUTE, first.end)

    sessions = []
    for slot in targets:
        cursor = slot.start
        while slot.end - cursor >= MINUTE and remaining:
            topic = next(iter(remaining))
            quota = remaining.pop(topic)
            duration = min(limit, quota, (slot.end - cursor) // MINUTE)
            end = cursor + duration * MINUTE
            sessions.append(StudySession(topic, objectives[topic], cursor, end))
            if duration < quota:
                remaining[topic] = quota - duration
            cursor = end
        if not remaining:
            break
    return sessions


def violations(
    sessions: list[StudySession], slots: list[Window], activity: AcademicActivity, limit: int,
) -> list[str]:
    errors = []
    previous_end = None
    for session in sorted(sessions, key=lambda item: item.start):
        if session.topic not in activity.topics or not session.objective.strip():
            errors.append("Tema u objetivo inválido")
        duration = session.end - session.start
        if not MINUTE <= duration <= limit * MINUTE or duration % MINUTE:
            errors.append("Duración fuera del límite")
        if session.end > activity.due_date:
            errors.append("Sesión posterior a la fecha límite")
        if not any(slot.start <= session.start < session.end <= slot.end for slot in slots):
            errors.append("Sesión fuera de disponibilidad o con conflicto")
        if previous_end is not None and session.start < previous_end:
            errors.append("Sesiones superpuestas")
        previous_end = max(previous_end or session.end, session.end)
    return list(dict.fromkeys(errors))
