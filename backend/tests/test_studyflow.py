import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo
from uuid import uuid4

import httpx
import pytest
from icalendar import Calendar
from sqlalchemy import text

from app.agents import workflow
from app.agents.workflow import MAX_PROPOSALS, OPERATIONS, ObjectiveProposal
from app.planning.application import services as planning_services


def create_subject(client):
    response = client.post("/subjects", json={"name": "Cálculo", "code": "MAT01"})
    assert response.status_code == 201, response.text
    return response.json()


def date_at(days, hour):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    ).isoformat()


def activity_payload(subject_id):
    return {
        "subject_id": subject_id, "title": "Parcial de cálculo", "type": "exam",
        "due_date": date_at(3, 10), "difficulty": 4,
        "topics": ["Integrales", "Derivadas"], "estimated_hours": 2, "priority": 4,
    }


@pytest.fixture
def activity(client):
    response = client.post("/activities", json=activity_payload(create_subject(client)["id"]))
    assert response.status_code == 201, response.text
    return response.json()


def plan_payload(activity):
    return {
        "activity_id": activity["id"], "timezone": "America/Bogota", "mode": "deterministic",
        "availability": [{"start": date_at(2, 16), "end": date_at(2, 21)}],
        "busy": [{"start": date_at(2, 16), "end": date_at(2, 17)}],
        "max_session_minutes": 30,
    }


def test_subject_crud(client):
    subject = create_subject(client)
    path = f"/subjects/{subject['id']}"
    assert client.get(path).json() == subject
    assert subject in client.get("/subjects").json()
    assert client.post("/subjects", json=subject).status_code == 409
    assert client.post("/subjects", json={"name": "   ", "code": "A"}).status_code == 422
    update = client.put(path, json={"name": "  Cálculo II  ", "code": "MAT02"})
    assert update.status_code == 200
    assert update.json()["name"] == "Cálculo II"
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.delete(path).status_code == 404


def test_migration_retains_existing_subject_and_persists_new_records(client, engine):
    assert client.get("/subjects").json()[0]["code"] == "LEGACY"
    subject = create_subject(client)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT code FROM subjects WHERE id = :id"), {"id": subject["id"]}
        ).scalar_one() == subject["code"]
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0004_personal_schedule"


def test_activity_crud_and_relationship(client, activity):
    subject_path = f"/subjects/{activity['subject_id']}"
    path = f"/activities/{activity['id']}"
    assert client.get(path).json() == activity
    assert activity in client.get("/activities").json()
    assert client.delete(subject_path).status_code == 409
    payload = activity_payload(activity["subject_id"])
    assert client.post("/activities", json={**payload, "subject_id": 9999}).status_code == 404
    assert client.post("/activities", json={**payload, "difficulty": 6}).status_code == 422
    assert client.post("/activities", json={**payload, "topics": ["A", " a "]}).status_code == 422
    assert client.post("/activities", json={**payload, "due_date": "2050-01-01T10:00:00"}).status_code == 422
    updated = client.put(path, json={**payload, "title": "Entrega", "type": "assignment"})
    assert updated.status_code == 200
    assert updated.json()["type"] == "assignment"
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.delete(subject_path).status_code == 204


def test_plan_conflicts_approval_and_export(client, activity):
    data = plan_payload(activity)
    first = client.post("/plans", json=data)
    second = client.post("/plans", json=data)
    assert first.status_code == second.status_code == 201, first.text
    plan = first.json()
    assert plan["status"] == "draft" and plan["tools_used"] == []
    assert plan["missing_minutes"] == 0
    assert len(plan["sessions"]) == 4
    assert all(item["duration_minutes"] == 30 for item in plan["sessions"])
    assert {item["topic"] for item in plan["sessions"]} == set(activity["topics"])
    assert datetime.fromisoformat(plan["sessions"][0]["start"]) >= datetime.fromisoformat(date_at(2, 17))
    base = f"/plans/{plan['id']}"
    assert client.get(base).json() == plan
    assert client.get(base + "/calendar.ics").status_code == 409
    approved = client.post(base + "/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert client.post(base + "/approve").status_code == 200
    rejected = client.post(f"/plans/{second.json()['id']}/approve")
    assert rejected.status_code == 409
    later = client.post("/plans", json=data).json()
    assert datetime.fromisoformat(later["sessions"][0]["start"]) >= datetime.fromisoformat(plan["sessions"][-1]["end"])
    activity_url = f"/activities/{activity['id']}"
    assert client.put(activity_url, json={
        **activity_payload(activity["subject_id"]), "due_date": date_at(1, 12),
    }).status_code == 409
    assert client.delete(activity_url).status_code == 409
    response = client.get(base + "/calendar.ics")
    assert response.status_code == 200
    events = Calendar.from_ical(response.content).walk("VEVENT")
    assert len(events) == 4
    assert len({str(event["uid"]) for event in events}) == 4
    assert events[0].decoded("dtstart") == datetime.fromisoformat(plan["sessions"][0]["start"])
    assert str(events[0]["summary"]).startswith(activity["title"])
    assert str(events[0]["description"]) == plan["sessions"][0]["objective"]
    assert str(events[0]["X-STUDYFLOW-SUBJECT"]) == "Cálculo"
    assert str(Calendar.from_ical(response.content)["X-WR-TIMEZONE"]) == "America/Bogota"


def test_deadline_partial_and_no_space(client, activity):
    data = plan_payload(activity)
    data["availability"] = [{"start": date_at(3, 9), "end": date_at(3, 12)}]
    partial = client.post("/plans", json=data)
    assert partial.status_code == 201, partial.text
    plan = partial.json()
    assert plan["missing_minutes"] == 60 and plan["reasons"]
    assert plan["sessions"][-1]["end"] == activity["due_date"]
    data["availability"] = [{"start": date_at(3, 10), "end": date_at(3, 12)}]
    unavailable = client.post("/plans", json=data)
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "unavailable"
    assert unavailable.json()["id"] is None and unavailable.json()["missing_minutes"] == 120
    data["availability"][0]["end"] = date_at(3, 8)
    assert client.post("/plans", json=data).status_code == 422


def bogota_at(day, hour):
    return datetime(2026, 11, day, hour, tzinfo=ZoneInfo("America/Bogota"))


@pytest.fixture
def partial_three(client, monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = bogota_at(25, 12)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(planning_services, "datetime", FrozenDateTime)
    payload = {
        **activity_payload(create_subject(client)["id"]),
        "title": "parcial 3",
        "due_date": bogota_at(26, 18).isoformat(),
        "topics": ["Rango", "Método de Gauss-Jordan", "Base y dimensión"],
        "estimated_hours": 3,
        "priority": 5,
    }
    created = client.post("/activities", json=payload)
    assert created.status_code == 201, created.text
    return {
        "activity_id": created.json()["id"],
        "timezone": "America/Bogota",
        "availability": [
            {"start": bogota_at(day, 17).isoformat(), "end": bogota_at(day, 20).isoformat()}
            for day in range(26, 30)
        ],
        "busy": [{"start": bogota_at(26, 18).isoformat(), "end": bogota_at(26, 19).isoformat()}],
        "mode": "agent",
        "max_session_minutes": 60,
    }


OBJECTIVES = {
    "topic_1": {"objective": "Calcular el rango de tres matrices triangulares", "study_priority": 3},
    "topic_2": {"objective": "Resolver tres sistemas con el método de Gauss-Jordan", "study_priority": 5},
    "topic_3": {"objective": "Encontrar una base y calcular su dimensión", "study_priority": 1},
}


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def with_structured_output(self, schema, *, method):
        assert issubclass(schema, ObjectiveProposal) and method == "json_schema"
        assert set(schema.model_json_schema()["required"]) == set(OBJECTIVES)
        return self

    def invoke(self, messages):
        context = json.loads(messages[-1][1])
        assert context["available_minutes"] == 60
        assert context["max_session_minutes"] == 60
        assert set(context["topics"]) == set(OBJECTIVES)
        self.calls += 1
        return next(self.responses)


def assert_partial_three(client, response):
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["mode"] == "agent" and plan["status"] == "draft"
    assert plan["tools_used"] == list(OPERATIONS)
    assert plan["missing_minutes"] == 120
    assert {item["topic"] for item in plan["coverage"]} == {"Rango", "Método de Gauss-Jordan", "Base y dimensión"}
    assert sum(item["required_minutes"] for item in plan["coverage"]) == 180
    assert sum(item["planned_minutes"] for item in plan["coverage"]) == 60
    previous_end = bogota_at(26, 17)
    for session in plan["sessions"]:
        start = datetime.fromisoformat(session["start"]).astimezone(ZoneInfo("America/Bogota"))
        end = datetime.fromisoformat(session["end"]).astimezone(start.tzinfo)
        assert previous_end <= start < end <= bogota_at(26, 18)
        assert start.date() == end.date()
        assert bogota_at(start.day, 17) <= start < end <= bogota_at(start.day, 20)
        assert end <= bogota_at(26, 18) or start >= bogota_at(26, 19)
        assert 1 <= session["duration_minutes"] <= 60
        previous_end = end
    assert previous_end == bogota_at(26, 18)
    assert client.get(f"/plans/{plan['id']}").json() == plan
    return plan


def test_langgraph_completes_partial_three_without_model_tool_calls(client, partial_three, monkeypatch, caplog):
    model = ScriptedModel([OBJECTIVES])
    monkeypatch.setattr(workflow, "ollama_model", lambda: model)
    with caplog.at_level("INFO", logger="uvicorn.error"):
        plan = assert_partial_three(client, client.post("/plans", json=partial_three))
    assert model.calls == 1
    assert plan["sessions"][0]["objective"] == OBJECTIVES["topic_2"]["objective"]
    events = [
        json.loads(record.message) for record in caplog.records
        if record.message.startswith('{"event": "studyflow.plan.step"')
    ]
    assert [event["step"] for event in events] == [
        *OPERATIONS[:2], "propose_objectives", *OPERATIONS[2:], "run_agent", "validate_before_save", "save_plan",
    ]
    assert len({event["run_id"] for event in events}) == 1
    assert all(event["outcome"] == "ok" and event["duration_ms"] >= 0 for event in events)
    assert events[-2]["violation_count"] == 0 and events[-1]["saved"]
    assert "Gauss-Jordan" not in caplog.text


@pytest.mark.parametrize("recover", [True, False])
def test_invalid_proposals_have_one_retry(client, partial_three, monkeypatch, recover):
    invalid = {"topic_1": OBJECTIVES["topic_1"], "topic_2": OBJECTIVES["topic_2"]}
    model = ScriptedModel([invalid, OBJECTIVES if recover else invalid])
    monkeypatch.setattr(workflow, "ollama_model", lambda: model)
    response = client.post("/plans", json=partial_three)
    assert model.calls == MAX_PROPOSALS
    if recover:
        assert_partial_three(client, response)
    else:
        assert response.status_code == 502, response.text
        assert client.get("/plans").json() == []


def test_final_calendar_guard_blocks_save_after_graph(client, partial_three, monkeypatch):
    model = ScriptedModel([OBJECTIVES])
    monkeypatch.setattr(workflow, "ollama_model", lambda: model)
    allocate = planning_services.allocate

    def introduce_conflict(*args):
        sessions = allocate(*args)
        sessions[0] = replace(sessions[0], end=bogota_at(26, 19))
        return sessions

    monkeypatch.setattr(planning_services, "allocate", introduce_conflict)
    response = client.post("/plans", json=partial_three)
    assert response.status_code == 409, response.text
    assert client.get("/plans").json() == []


@pytest.mark.skipif(os.getenv("STUDYFLOW_TEST_OLLAMA") != "1", reason="Requires a running Ollama model")
def test_langgraph_with_ollama(client, partial_three):
    without_hours(client, partial_three["activity_id"])
    response = client.post("/plans", json=partial_three)
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["estimate_source"] == "agent"
    assert plan["required_minutes"] == sum(item["suggested_minutes"] for item in plan["coverage"])
    assert len(plan["coverage"]) == 3 and 0 < plan["planned_minutes"] <= 60
    assert all(item["rationale"] for item in plan["coverage"])
    assert plan["assumptions"]


def test_model_connection_error_returns_503_without_draft(client, activity, monkeypatch, caplog):
    class OfflineModel:
        def with_structured_output(self, schema, *, method):
            return self

        def invoke(self, messages):
            raise httpx.ConnectError("internal-token")

    monkeypatch.setattr(workflow, "ollama_model", OfflineModel)
    response = client.post("/plans", json={**plan_payload(activity), "mode": "agent"})
    assert response.status_code == 503, response.text
    assert "internal-token" not in caplog.text
    assert "ConnectError" in caplog.text
    assert client.get("/plans").json() == []


@pytest.mark.skipif(os.getenv("STUDYFLOW_TEST_POSTGRES") != "1", reason="Requires PostgreSQL locking")
def test_concurrent_postgres_approvals(client, activity):
    from concurrent.futures import ThreadPoolExecutor

    payload = plan_payload(activity)
    other_subject = client.post("/subjects", json={"name": "Analítica", "code": "ANA"}).json()
    other_activity = client.post("/activities", json=activity_payload(other_subject["id"])).json()
    other_payload = {**payload, "activity_id": other_activity["id"]}
    plans = [client.post("/plans", json=data).json() for data in (payload, other_payload)]

    def approve(plan):
        return client.post(f"/plans/{plan['id']}/approve").status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(approve, plans)) == [200, 409]
    saved = client.get('/plans').json()
    approved = next(plan for plan in saved if plan['status'] == 'approved')
    remaining = next(plan for plan in saved if plan['status'] == 'draft')
    next_plan = client.post('/plans', json={**payload, 'activity_id': remaining['activity_id']}).json()
    assert next_plan['sessions'][0]['start'] >= approved['sessions'][-1]['end']

def test_day_only_deadline_and_topic_identity(client, activity):
    payload = activity_payload(activity["subject_id"])
    del payload["due_date"]
    payload["due_day"] = "2026-11-26"
    payload["topics"].reverse()
    payload["topic_weights"] = {"Integrales": 5, "Derivadas": 1}
    response = client.put(f"/activities/{activity['id']}", json=payload)
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["topic_ids"] == activity["topic_ids"]
    assert changed["due_day"] == "2026-11-26"
    assert datetime.fromisoformat(changed["due_date"]) == bogota_at(27, 0)


def test_plan_history_keeps_weighted_coverage_and_reports_progress(client, activity, engine):
    payload = activity_payload(activity["subject_id"])
    payload["topic_weights"] = {"Integrales": 5, "Derivadas": 1}
    updated = client.put(f"/activities/{activity['id']}", json=payload)
    assert updated.status_code == 200
    progress_id = str(uuid4())
    response = client.post("/plans", json=plan_payload(activity), headers={"X-Plan-Progress": progress_id})
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["created_at"] and plan["required_minutes"] == 120
    coverage = {topic["topic"]: topic for topic in plan["coverage"]}
    assert coverage["Integrales"]["required_minutes"] > coverage["Derivadas"]["required_minutes"]
    assert client.get("/plans").json()[0] == plan
    events = client.get(f"/plans/progress/{progress_id}").json()["events"]
    assert events[-2:] == [{"step": "save_plan", "outcome": status} for status in ("running", "ok")]

    with engine.begin() as connection:
        connection.execute(text("UPDATE study_plans SET coverage = NULL, created_at = NULL WHERE id = :id"),
                           {"id": plan["id"]})
    legacy = client.get(f"/plans/{plan['id']}").json()
    assert legacy["created_at"] is None
    assert legacy["sessions"] == plan["sessions"]
    assert all(topic["required_minutes"] is None for topic in legacy["coverage"])

def without_hours(client, activity_id):
    path = f"/activities/{activity_id}"
    prior = client.get(path).json()
    body = {key: value for key, value in prior.items() if key not in {"id", "topic_ids", "estimated_hours"}}
    body["topic_details"][0]["priority"] = 5
    body["topic_details"][0]["mastery"] = 2
    response = client.put(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["estimated_hours"] is None
    return response.json()


def test_structured_topic_crud_and_legacy_ids(client, activity):
    legacy = activity["topic_details"][0]
    assert legacy["priority"] == 3 and legacy["mastery"] is None
    path = f"/activities/{activity['id']}"
    payload = activity_payload(activity["subject_id"])
    del payload["topics"]
    del payload["estimated_hours"]
    payload["topic_details"] = [{**legacy, "name": "Integrales impropias", "priority": 5, "mastery": 2},
                                {"name": "Series", "priority": 1}]
    result = client.put(path, json=payload)
    assert result.status_code == 200, result.text
    saved = client.get(path).json()
    assert saved["topics"] == ["Integrales impropias", "Series"]
    assert saved["topic_details"][0] == payload["topic_details"][0]
    assert saved["topic_details"][1]["id"]
    assert saved["estimated_hours"] is None
    payload["topic_details"] = [{**saved["topic_details"][1], "mastery": 6}]
    assert client.put(path, json=payload).status_code == 422
    payload["topic_details"][0]["mastery"] = 4
    assert client.put(path, json=payload).json()["topics"] == ["Series"]


def test_estimate_validation_retries_and_manual_adjustment(client, partial_three, monkeypatch):
    activity = without_hours(client, partial_three["activity_id"])
    valid = {key: {**objective, "required_minutes": 50, "rationale": "Practicar la técnica con ejemplos."}
             for key, objective in OBJECTIVES.items()}
    invalid = {**valid, "topic_1": {**valid["topic_1"], "required_minutes": 481}}
    model = ScriptedModel([invalid, valid, valid])
    monkeypatch.setattr(workflow, "ollama_model", lambda: model)
    created = client.post("/plans", json=partial_three)
    assert created.status_code == 201, created.text
    plan = created.json()
    assert model.calls == 2
    assert plan["required_minutes"] == 150 and plan["missing_minutes"] == 90
    assert plan["coverage"][0]["topic_id"] == activity["topic_details"][0]["id"]
    assert all(item["suggested_minutes"] == 50 and item["rationale"] for item in plan["coverage"])
    adjusted = client.post("/plans", json={**partial_three, "target_minutes": 90})
    assert adjusted.status_code == 201, adjusted.text
    assert adjusted.json()["required_minutes"] == 90
    assert all(item["suggested_minutes"] == 50 for item in adjusted.json()["coverage"])


def test_tracking_replacement_preserves_history_and_changes_deadline_on_approval(client, activity):
    payload = plan_payload(activity)
    plan = client.post("/plans", json=payload).json()
    source = f"/plans/{plan['id']}"
    assert client.post(source + "/approve").status_code == 200
    first, second, third = plan["sessions"][:3]
    tracker = source + f"/sessions/{first['id']}/tracking"
    assert client.patch(tracker, json={"status": "partial", "effective_minutes": first["duration_minutes"]}).status_code == 409
    tracked = client.patch(tracker, json={"status": "partial", "effective_minutes": 10})
    assert tracked.status_code == 200 and tracked.json()["completed_minutes"] == 10
    client.patch(source + f"/sessions/{second['id']}/tracking", json={"status": "completed"})
    client.patch(source + f"/sessions/{third['id']}/tracking", json={"status": "not_done"})
    replacement = {**payload, "replaces_plan_id": plan["id"], "proposed_due_date": date_at(3, 8)}
    draft = client.post("/plans", json=replacement)
    assert draft.status_code == 201, draft.text
    assert draft.json()["required_minutes"] == 110 - second["duration_minutes"]
    assert client.get(source).json()["status"] == "approved"
    assert client.get(f"/activities/{activity['id']}").json()["due_date"] == activity["due_date"]
    assert client.post("/plans", json=payload).json()["sessions"][0]["start"] >= plan["sessions"][-1]["end"]
    client.patch(tracker, json={"status": "partial", "effective_minutes": 15})
    assert client.post(f"/plans/{draft.json()['id']}/approve").status_code == 409
    renewed = client.post("/plans", json=replacement)
    assert renewed.status_code == 201, renewed.text
    approval = client.post(f"/plans/{renewed.json()['id']}/approve")
    assert approval.status_code == 200, approval.text
    assert approval.json()["required_minutes"] == 105 - second["duration_minutes"]
    old = client.get(source).json()
    assert old["status"] == "superseded"
    assert old["sessions"][0]["status"] == "replaced"
    assert old["sessions"][0]["effective_minutes"] == 15
    assert [event["after"]["minutes"] for event in old["sessions"][0]["tracking_history"]] == [10, 15]
    assert old["sessions"][1]["study_status"] == "completed"
    assert datetime.fromisoformat(client.get(f"/activities/{activity['id']}").json()["due_date"]) == datetime.fromisoformat(replacement["proposed_due_date"])
    assert client.post(f"/plans/{draft.json()['id']}/approve").status_code == 409

def test_draft_in_current_window_can_be_reviewed_before_approval(client, activity, monkeypatch):
    class Clock(datetime):
        instant = datetime.now(timezone.utc).replace(microsecond=0)

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)

    monkeypatch.setattr(planning_services, "datetime", Clock)
    start = Clock.instant - timedelta(minutes=15)
    end = Clock.instant + timedelta(hours=3)
    payload = {**plan_payload(activity), "availability": [{"start": start.isoformat(), "end": end.isoformat()}], "busy": []}
    created = client.post("/plans", json=payload)
    assert created.status_code == 201, created.text
    saved = created.json()
    assert datetime.fromisoformat(saved["sessions"][0]["start"]) >= Clock.instant + timedelta(minutes=5)
    Clock.instant += timedelta(minutes=1)
    approved = client.post(f"/plans/{saved['id']}/approve")
    assert approved.status_code == 200, approved.text

def test_estimate_without_available_slots_is_kept_without_reserving(client, partial_three):
    without_hours(client, partial_three["activity_id"])
    data = {**partial_three, "mode": "deterministic", "availability": [
        {"start": bogota_at(27, 17).isoformat(), "end": bogota_at(27, 20).isoformat()}
    ]}
    response = client.post("/plans", json=data)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["status"] == "unavailable" and saved["id"]
    assert not saved["sessions"] and saved["required_minutes"] == saved["missing_minutes"] > 0
    assert all(item["suggested_minutes"] for item in saved["coverage"])
    assert client.get(f"/plans/{saved['id']}").json() == saved
    assert client.post(f"/plans/{saved['id']}/approve").status_code == 409

def personal_for(payload, *, start="17:00", end="18:00", title="Transporte"):
    reference = datetime.fromisoformat(payload["availability"][0]["start"]).astimezone(ZoneInfo("America/Bogota"))
    return {"title": title, "day": reference.date().isoformat(), "start_time": start,
            "end_time": end, "description": "Viaje a casa", "category": "Transporte"}


def test_personal_crud_and_weekly_occurrences(client):
    block = {"title": "Trabajo", "day": "2026-11-23", "start_time": "17:00", "end_time": "18:00",
             "weekdays": [0, 2], "until": "2026-12-02", "description": "Turno"}
    created = client.post("/personal-blocks", json=block)
    assert created.status_code == 201, created.text
    saved = created.json()
    path = f"/personal-blocks/{saved['id']}"
    assert client.get(path).json() == saved
    assert client.get("/personal-blocks").json() == [saved]
    query = "/personal-blocks/occurrences?start=2026-11-25&end=2026-12-03"
    dates = [item["start"] for item in client.get(query).json()]
    assert dates == ["2026-11-25T17:00:00-05:00", "2026-11-30T17:00:00-05:00", "2026-12-02T17:00:00-05:00"]
    assert client.put(path, json={**block, "end_time": "16:50"}).status_code == 422
    assert client.put(path, json={**block, "weekdays": [2, 2]}).status_code == 422
    updated = client.put(path, json={**block, "weekdays": [2], "title": "Clases particulares"})
    assert updated.status_code == 200 and updated.json()["title"] == "Clases particulares"
    assert len(client.get(query).json()) == 2
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.get(query).json() == []


def calendar_case(activity):
    payload = plan_payload(activity)
    zone = ZoneInfo("America/Bogota")
    start = datetime.fromisoformat(payload["availability"][0]["start"]).astimezone(zone).replace(hour=16)
    end = start.replace(hour=20)
    return {**payload, "availability": [{"start": start.isoformat(), "end": end.isoformat()}], "busy": []}


def test_generation_avoids_personal_and_protects_approved_sessions(client, activity):
    payload = calendar_case(activity)
    commitment = personal_for(payload)
    block = client.post("/personal-blocks", json=commitment)
    assert block.status_code == 201, block.text
    result = client.post("/plans", json=payload)
    assert result.status_code == 201, result.text
    plan = result.json()
    zone = ZoneInfo("America/Bogota")
    cutoff = datetime.fromisoformat(commitment["day"] + "T17:00").replace(tzinfo=zone)
    upper = cutoff + timedelta(hours=1)
    assert all(not (datetime.fromisoformat(session["start"]) < upper and cutoff < datetime.fromisoformat(session["end"]))
               for session in plan["sessions"])
    assert any(datetime.fromisoformat(session["start"]) >= upper for session in plan["sessions"])
    approved = client.post(f"/plans/{plan['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert all(item["status"] == "scheduled" for item in approved.json()["sessions"])
    collision = client.put(f"/personal-blocks/{block.json()['id']}",
                           json={**commitment, "start_time": "16:00", "end_time": "17:00"})
    assert collision.status_code == 409 and "Una alternativa" in collision.json()["detail"]
    assert client.get(f"/plans/{plan['id']}").json() == approved.json()
    assert client.get(f"/personal-blocks/{block.json()['id']}").json() == block.json()


def test_approval_revalidates_personal_blocks_created_after_draft(client, activity):
    payload = calendar_case(activity)
    plan = client.post("/plans", json=payload).json()
    block = client.post("/personal-blocks", json=personal_for(payload, start="16:00", end="16:30"))
    assert block.status_code == 201, block.text
    result = client.post(f"/plans/{plan['id']}/approve")
    assert result.status_code == 409 and "compromiso personal" in result.json()["detail"]
    assert client.get(f"/plans/{plan['id']}").json()["status"] == "draft"
    assert client.delete(f"/personal-blocks/{block.json()['id']}").status_code == 204
    assert client.post(f"/plans/{plan['id']}/approve").status_code == 200


def test_generation_replay_and_regeneration_lineage(client, activity):
    payload = plan_payload(activity)
    headers = {"X-Plan-Progress": str(uuid4())}
    first = client.post("/plans", json=payload, headers=headers)
    second = client.post("/plans", json=payload, headers=headers)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json() == second.json()
    assert len(client.get("/plans").json()) == 1
    assert client.post("/plans", json={**payload, "max_session_minutes": 45}, headers=headers).status_code == 409
    derived = client.post("/plans", json={**payload, "derived_from_plan_id": first.json()["id"]})
    assert derived.status_code == 201, derived.text
    history = client.get("/plans").json()
    assert [item["id"] for item in history] == [derived.json()["id"], first.json()["id"]]
    assert history[0]["derived_from_plan_id"] == history[1]["id"]
    assert history[0]["replaces_plan_id"] is None


@pytest.mark.skipif(os.getenv("STUDYFLOW_TEST_POSTGRES") != "1", reason="Requires PostgreSQL locking")
def test_personal_create_and_plan_approval_serialize(client, activity):
    from concurrent.futures import ThreadPoolExecutor

    payload = calendar_case(activity)
    plan = client.post("/plans", json=payload).json()
    block = personal_for(payload, start="16:00", end="16:30")
    with ThreadPoolExecutor(max_workers=2) as executor:
        personal = executor.submit(client.post, "/personal-blocks", json=block)
        approval = executor.submit(client.post, f"/plans/{plan['id']}/approve")
        codes = (personal.result().status_code, approval.result().status_code)
    assert codes in {(201, 409), (409, 200)}

@pytest.mark.skipif(os.getenv("STUDYFLOW_TEST_POSTGRES") != "1", reason="Requires concurrent PostgreSQL sessions")
def test_same_generation_repeated_concurrently_creates_only_one_plan(client, activity):
    from concurrent.futures import ThreadPoolExecutor

    payload = plan_payload(activity)
    headers = {"X-Plan-Progress": str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(client.post, "/plans", json=payload, headers=headers) for _ in range(2)]
        statuses = sorted(future.result().status_code for future in futures)
    assert statuses in ([200, 201], [201, 409])
    saved = client.get("/plans").json()
    assert len(saved) == 1
    replay = client.post("/plans", json=payload, headers=headers)
    assert replay.status_code == 200 and replay.json()["id"] == saved[0]["id"]


def test_agent_receives_only_free_minutes_after_personal_commitments(client, partial_three, monkeypatch):
    commitment = client.post("/personal-blocks", json={
        "title": "Transporte", "day": "2026-11-26", "start_time": "17:15", "end_time": "17:30"
    })
    assert commitment.status_code == 201, commitment.text

    class ObservedModel(ScriptedModel):
        def invoke(self, messages):
            context = json.loads(messages[-1][1])
            assert context["available_minutes"] == 45
            return next(self.responses)

    monkeypatch.setattr(workflow, "ollama_model", lambda: ObservedModel([OBJECTIVES]))
    result = client.post("/plans", json=partial_three)
    assert result.status_code == 201, result.text
    plan = result.json()
    assert plan["mode"] == "agent" and plan["planned_minutes"] == 45
    assert any("compromisos personales ocuparon 15" in reason for reason in plan["reasons"])
