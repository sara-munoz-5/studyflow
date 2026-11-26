from datetime import datetime, timedelta
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from calendar_view import PALETTE, ZONE, block_rows, calendar_entries, pack_windows


SUBJECT = {"id": 1, "name": "Arquitectura de software", "code": "ARQ", "description": "Diseño de sistemas"}


def activity(kind="exam"):
    return {"id": 3, "subject_id": 1, "title": "Parcial 3", "type": kind, "status": "pending",
            "due_date": "2026-11-26T23:00:00Z", "topics": ["SOLID", "C4"], "estimated_hours": 3,
            "difficulty": 4, "priority": 5}


def plan(status="approved"):
    return {
        "id": 4, "activity_id": 3, "status": status, "mode": "deterministic", "created_at": "2026-11-25T16:00:00Z",
        "planned_minutes": 35, "missing_minutes": 145, "required_minutes": 180, "tools_used": [], "reasons": [],
        "coverage": [{"topic": "SOLID", "planned_minutes": 35, "required_minutes": 100,
                      "status": "partial", "objective": "Aplicar SOLID"}],
        "sessions": [{"id": 5, "start": "2026-11-26T22:00:00Z", "end": "2026-11-26T22:35:00Z",
                      "topic": "SOLID", "objective": "Aplicar SOLID en un sistema con dos adaptadores",
                      "duration_minutes": 35, "status": "scheduled"}],
    }


def test_calendar_category_colors_and_bogota_time():
    for kind, (strong, light, _) in PALETTE.items():
        principal, study = calendar_entries([SUBJECT], [activity(kind)], [plan()])[0]
        assert principal["backgroundColor"] == strong and study["backgroundColor"] == light
        assert principal["start"] == "2026-11-26T18:00:00"
        assert study["start"] == "2026-11-26T17:00:00"
        assert study["end"] == "2026-11-26T17:35:00"
        assert study["title"].startswith("Estudio")
    deadline = {**activity("assignment"), "due_day": "2026-11-26"}
    items, _ = calendar_entries([SUBJECT], [deadline], [plan("draft")])
    assert len(items) == 1 and items[0]["allDay"] and items[0]["start"] == "2026-11-26"


def test_availability_blocks_pack_contiguous_hours():
    start = datetime(2026, 11, 26, 17, tzinfo=ZONE)
    end = datetime(2026, 11, 26, 20, tzinfo=ZONE)
    slots = list(block_rows(start, end))
    assert len(slots) == 6
    assert pack_windows(slots[2:4]) == [{"start": "2026-11-26T18:00:00-05:00",
                                          "end": "2026-11-26T19:00:00-05:00"}]


def test_subject_navigation_and_plan_history(monkeypatch):
    def request(method, url, **kwargs):
        path = httpx.URL(url).path
        return httpx.Response(200, json={"/subjects": [SUBJECT], "/activities": [activity()],
                                         "/plans": [plan("draft")]}[path])

    monkeypatch.setattr(httpx, "request", request)
    ui = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=30).run()
    assert not ui.exception
    assert ui.title[0].value == "Mis materias"
    ui.button(key="open-1").click().run()
    assert not ui.exception
    assert ui.title[0].value == SUBJECT["name"]
    assert ui.button(key="generate-3").label == "Generar plan"
    ui.get("segmented_control")[0].set_value("Planes de estudio").run()
    assert not ui.exception
    ui.button(key="plan-4").click().run()
    assert not ui.exception
    assert any(item.value == "Aplicar SOLID en un sistema con dos adaptadores" for item in ui.markdown)
    assert any(button.label == "Aceptar plan" for button in ui.button)
    assert any(button.label == "Modificar o regenerar" for button in ui.button)

def test_activity_table_preserves_topic_ids_and_mastery(monkeypatch):
    rows = [{"id": "033b3aa7-1c60-400b-a19e-474ef8699a20", "name": "SOLID", "priority": 5, "mastery": 2},
            {"id": "a57b8995-9762-442c-875b-2a4d1826eaba", "name": "Matrices | 5", "priority": 1, "mastery": None}]
    existing = {**activity(), "topics": [row["name"] for row in rows], "topic_details": rows, "estimated_hours": None}
    edits = []

    def request(method, url, **kwargs):
        path = httpx.URL(url).path
        if method == "PUT" and path == "/activities/3":
            edits.append(kwargs["json"])
            return httpx.Response(200, json=existing)
        return httpx.Response(200, json={"/subjects": [SUBJECT], "/activities": [existing], "/plans": []}[path])

    monkeypatch.setattr(httpx, "request", request)
    ui = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=30).run()
    ui.button(key="open-1").click().run()
    ui.button(key="activity-edit-3").click().run()
    assert not ui.exception
    assert len(ui.dataframe) == 1
    assert not any(item.label == "Horas estimadas" for item in ui.number_input)
    next(button for button in ui.button if button.label == "Guardar actividad").click().run()
    assert not ui.exception
    assert edits[0]["topic_details"] == rows
    assert edits[0]["estimated_hours"] is None


def test_visual_availability_to_draft_and_approval(monkeypatch):
    saved = []
    payloads = []
    pending = {**activity(), "due_date": (datetime.now(ZONE) + timedelta(days=3)).isoformat()}

    def request(method, url, **kwargs):
        path = httpx.URL(url).path
        if method == "POST" and path == "/plans":
            payloads.append(kwargs["json"])
            saved.append(plan("draft"))
            return httpx.Response(201, json=saved[-1])
        if method == "POST" and path == "/plans/4/approve":
            saved[0]["status"] = "approved"
            return httpx.Response(200, json=saved[0])
        if path.startswith("/plans/progress/"):
            return httpx.Response(200, json={"events": []})
        return httpx.Response(200, json={"/subjects": [SUBJECT], "/activities": [pending], "/plans": saved}[path])

    monkeypatch.setattr(httpx, "request", request)
    ui = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=30).run()
    ui.button(key="open-1").click().run()
    ui.button(key="generate-3").click().run()
    assert not ui.exception
    next(radio for radio in ui.radio if radio.label == "Modo").set_value("deterministic")
    ui.checkbox[0].check().run()
    next(button for button in ui.button if button.label == "Generar borrador").click().run()
    if not any(button.label == "Aceptar plan" for button in ui.button):
        ui.run()
    assert not ui.exception
    assert payloads[0]["activity_id"] == 3 and payloads[0]["mode"] == "deterministic"
    busy = payloads[0]["busy"]
    assert len(busy) == 1
    assert local_time(busy[0]["end"]) - local_time(busy[0]["start"]) == timedelta(minutes=30)
    next(button for button in ui.button if button.label == "Aceptar plan").click().run()
    assert not ui.exception
    assert saved[0]["status"] == "approved"
    assert any(button.label == "Preparar archivo .ics" for button in ui.button)


def local_time(value):
    return datetime.fromisoformat(value).astimezone(ZONE)

def test_calendar_keeps_completed_history_without_replaced_slots():
    original = plan("superseded")
    completed = {**original["sessions"][0], "study_status": "completed"}
    replaced = {**completed, "id": 6, "study_status": "partial", "status": "replaced"}
    original["sessions"] = [completed, replaced]
    events, _ = calendar_entries([SUBJECT], [activity()], [original, plan("draft")])
    assert {item["id"] for item in events} == {"activity-3", "session-5"}
    assert events[1]["title"].endswith("Completada")
