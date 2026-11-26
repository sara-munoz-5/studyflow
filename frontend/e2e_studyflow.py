"""Run only against a fresh, isolated instance of StudyFlow."""
import argparse
import os
from datetime import datetime, time, timedelta
from time import monotonic, sleep
from zoneinfo import ZoneInfo

import httpx
from playwright.sync_api import expect, sync_playwright


def wait_for(url):
    deadline = monotonic() + 90
    while monotonic() < deadline:
        try:
            if httpx.get(url, timeout=5).is_success:
                return
        except httpx.RequestError:
            pass
        sleep(2)
    raise RuntimeError(f"Servicio de prueba no disponible en {url}")


def exercise(api, ui):
    wait_for(f"{api}/health/db")
    wait_for(f"{ui}/_stcore/health")
    assert httpx.get(f"{api}/subjects").json() == [], "Usa una instancia de prueba vacía"
    zone = ZoneInfo("America/Bogota")
    today = datetime.now(zone).date()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("STUDYFLOW_TEST_CHROMIUM"), headless=True,
        )
        page = browser.new_page(timezone_id=zone.key)
        page.set_default_timeout(45000)
        expect.set_options(timeout=45000)
        page.goto(ui)
        page.get_by_role("button", name="Crear materia").click()
        page.get_by_label("Nombre", exact=True).fill("Arquitectura E2E")
        page.get_by_label("Código", exact=True).fill("E2E")
        page.get_by_role("button", name="Guardar materia").click()
        page.get_by_role("button", name="Abrir materia").click()
        page.get_by_role("button", name="Crear actividad").click()
        expect(page.get_by_text("Temas de estudio", exact=True)).to_be_visible()
        expect(page.get_by_text("Horas estimadas", exact=True)).to_have_count(0)
        page.get_by_role("button", name="Volver a actividades").click()

        subject = httpx.get(f"{api}/subjects").json()[0]
        response = httpx.post(f"{api}/activities", json={
            "subject_id": subject["id"], "title": "Parcial E2E", "type": "exam",
            "due_date": datetime.combine(today + timedelta(days=5), time(20), zone).isoformat(),
            "difficulty": 3, "priority": 4,
            "topic_details": [{"name": "Puertos y adaptadores", "priority": 5, "mastery": 2},
                              {"name": "Pruebas de contrato", "priority": 3}],
        })
        response.raise_for_status()
        assert response.json()["estimated_hours"] is None

        page.reload()
        page.get_by_role("button", name="Abrir materia").click()
        page.get_by_role("button", name="Generar plan").click()
        page.get_by_text("Planificador sin IA", exact=True).click()
        page.get_by_role("button", name="Generar borrador").click()
        accept = page.get_by_role("button", name="Aceptar plan")
        expect(accept).to_be_visible()
        draft = httpx.get(f"{api}/plans").json()[0]
        assert draft["status"] == "draft" and draft["sessions"]
        accept.click()
        expect(page.get_by_text("Plan aprobado. Sus sesiones ya aparecen en Mi calendario.")).to_be_visible()
        approved = httpx.get(f"{api}/plans/{draft['id']}").json()
        assert approved["status"] == "approved"

        scheduled = datetime.fromisoformat(approved["sessions"][0]["start"]).astimezone(zone).date()
        page.get_by_text("Mi calendario", exact=True).first.click()
        frame = page.frame_locator('iframe[title*="streamlit_calendar"]')
        expect(frame.locator(".fc-timeGridWeek-view")).to_be_visible()
        frame.locator(".fc-timeGridDay-button").click()
        for _ in range((scheduled - today).days):
            frame.locator(".fc-next-button").click()
        expect(frame.locator(".fc-timeGridDay-view .fc-timegrid-event").filter(has_text="Estudio").first).to_be_visible()
        frame.locator(".fc-timeGridWeek-button").click()
        expect(frame.locator(".fc-timeGridWeek-view .fc-timegrid-event").filter(has_text="Estudio").first).to_be_visible()
        frame.locator(".fc-dayGridMonth-button").click()
        event = frame.locator(".fc-dayGridMonth-view .fc-daygrid-event").filter(has_text="Estudio").first
        expect(event).to_be_visible()
        event.click()
        expect(page.get_by_text("Registrar progreso", exact=True)).to_be_visible()
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--ui", required=True)
    args = parser.parse_args()
    exercise(args.api, args.ui)
    print("E2E: actividad sin horas, borrador visible, aprobación y sesiones en día, semana y mes.")
