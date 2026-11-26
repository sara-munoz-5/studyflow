from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Bogota")
KINDS = {"exam": "Parcial", "assignment": "Entrega", "laboratory": "Laboratorio", "project": "Proyecto"}
PALETTE = {
    "exam": ("#a32642", "#fce4e9", "#68182a"),
    "assignment": ("#2355a3", "#deebff", "#183964"),
    "laboratory": ("#663ea0", "#eee4ff", "#472672"),
    "project": ("#9b4414", "#ffead8", "#642d12"),
}
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")


def local(value):
    return datetime.fromisoformat(value).astimezone(ZONE)


def day_label(day):
    return f"{WEEKDAYS[day.weekday()].capitalize()} {day.day} de {MONTHS[day.month - 1]}"


def intersects(start, end, other_start, other_end):
    return start < other_end and other_start < end


def pack_windows(windows):
    merged = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return [{"start": start.isoformat(), "end": end.isoformat()} for start, end in merged]


def calendar_entries(subjects, activities, plans):
    subjects = {item["id"]: item for item in subjects}
    activities = {item["id"]: item for item in activities}
    events, details = [], {}

    def add(event_id, activity, title, start, end=None, all_day=False, session=None, plan=None):
        strong, light, ink = PALETTE[activity["type"]]
        subject = subjects[activity["subject_id"]]
        event = {
            "id": event_id, "title": title, "start": start, "allDay": all_day,
            "backgroundColor": light if session else strong, "borderColor": strong,
            "textColor": ink if session else "#ffffff",
        }
        if end:
            event["end"] = end
        events.append(event)
        details[event_id] = {"subject": subject, "activity": activity, "session": session, "plan": plan}

    # Use Bogotá wall time on both sides of the iframe regardless of the browser's time zone.
    def wall(value):
        return local(value).replace(tzinfo=None).isoformat()

    for activity in activities.values():
        if activity["status"] == "cancelled":
            continue
        day = activity.get("due_day")
        kind = KINDS[activity["type"]]
        add(f"activity-{activity['id']}", activity, f"{kind} · {activity['title']}",
            day or wall(activity["due_date"]), all_day=bool(day))

    for plan in plans:
        if plan["status"] not in {"approved", "superseded"}:
            continue
        activity = activities[plan["activity_id"]]
        for session in plan["sessions"]:
            study = session.get("study_status", "pending")
            if plan["status"] == "superseded" and (session["status"] == "replaced" or study not in {"completed", "partial"}):
                continue
            suffix = {"completed": " · Completada", "partial": " · Parcial", "not_done": " · No realizada"}.get(study, "")
            add(f"session-{session['id']}", activity, f"Estudio · {session['topic']}{suffix}", wall(session["start"]),
                wall(session["end"]), session=session, plan=plan)
    return events, details


def block_rows(start, end):
    while start < end:
        next_start = min(start + timedelta(minutes=30), end)
        yield start, next_start
        start = next_start
