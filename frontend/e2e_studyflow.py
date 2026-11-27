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
    assert httpx.get(f"{api}/personal-blocks").json() == [], "Usa una instancia de prueba vacía"
    zone = ZoneInfo("America/Bogota")
    today = datetime.now(zone).date()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("STUDYFLOW_TEST_CHROMIUM"), headless=True,
        )
        page = browser.new_page(timezone_id="Pacific/Auckland")
        page.set_default_timeout(45000)
        expect.set_options(timeout=45000)
        page.goto(ui)
        page.get_by_role("button", name="Crear materia").click()
        page.get_by_label("Nombre", exact=True).fill("Arquitectura E2E")
        page.get_by_label("Código", exact=True).fill("E2E")
        page.get_by_role("button", name="Guardar materia").click()
        page.get_by_role("button", name="Abrir materia").click()

        subject = httpx.get(f"{api}/subjects").json()[0]
        response = httpx.post(f"{api}/activities", json={
            "subject_id": subject["id"], "title": "Parcial E2E", "type": "exam",
            "due_date": datetime.combine(today + timedelta(days=5), time(20), zone).isoformat(),
            "difficulty": 3, "priority": 4,
            "topic_details": [{"name": topic, "priority": 5 if index == 0 else 3, "mastery": 2}
                              for index, topic in enumerate((
                                  "Puertos y adaptadores", "Pruebas de contrato", "Inyección de dependencias",
                                  "Casos de uso", "Transacciones", "Modelado del dominio",
                                  "Persistencia", "Mensajería",
                              ))],
        })
        response.raise_for_status()
        assert response.json()["estimated_hours"] is None

        page.get_by_text("Mi disponibilidad", exact=True).first.click()
        page.get_by_role("button", name="Crear compromiso", exact=True).click()
        page.get_by_label("Título del compromiso", exact=True).fill("Transporte E2E")
        page.get_by_label("Categoría (opcional)", exact=True).fill("Transporte")
        page.get_by_label("Descripción (opcional)", exact=True).fill("Viaje de prueba")
        page.get_by_role("button", name="Guardar compromiso").click()
        expect(page.get_by_role("heading", name="Transporte E2E")).to_be_visible()
        block = httpx.get(f"{api}/personal-blocks").json()[0]
        assert block["start_time"] == "17:00:00" and block["end_time"] == "18:00:00"

        # Extend the series so a future slot is exercised even when today is already over.
        block_id = block.pop("id")
        httpx.put(f"{api}/personal-blocks/{block_id}", json={
            **block, "weekdays": list(range(7)), "until": (today + timedelta(days=3)).isoformat(),
        }).raise_for_status()
        httpx.post(f"{api}/subjects", json={"name": "Materia secundaria", "code": "SEC"}).raise_for_status()
        page.get_by_text("Mis materias", exact=True).first.click()
        page.get_by_role("button", name="← Mis materias", exact=True).click()
        page.get_by_role("button", name="Abrir materia").first.click()
        page.get_by_role("button", name="Generar plan").click()
        page.get_by_text("Planificador sin IA", exact=True).click()
        page.get_by_role("spinbutton", name="hora, Inicio diario").press("ArrowDown")
        expect(page.get_by_text("16:00–16:30", exact=True)).to_be_visible()
        page.get_by_role("button", name="Generar borrador").click()
        accept = page.get_by_role("button", name="Aceptar plan")
        expect(accept).to_be_visible()
        draft = httpx.get(f"{api}/plans").json()[0]
        assert draft["status"] == "draft" and draft["sessions"]
        assert all(datetime.fromisoformat(item["start"]).astimezone(zone).time() == time(16)
                   and datetime.fromisoformat(item["end"]).astimezone(zone).time() == time(20)
                   for item in draft["availability"])
        times = [(datetime.fromisoformat(item["start"]).astimezone(zone),
                  datetime.fromisoformat(item["end"]).astimezone(zone)) for item in draft["sessions"]]
        assert all(not (start < datetime.combine(start.date(), time(18), zone) and
                        datetime.combine(start.date(), time(17), zone) < end) for start, end in times)
        assert any(start.time() < time(17) for start, _ in times)
        assert any(start.time() >= time(18) for start, _ in times)

        accept.click()
        expect(page.get_by_text("Plan aprobado. Sus sesiones ya aparecen en Mi calendario.")).to_be_visible()
        approved = httpx.get(f"{api}/plans/{draft['id']}").json()
        assert approved["status"] == "approved"

        page.get_by_role("button", name="Ver sesiones en Mi calendario").click()
        frame = page.frame_locator('iframe[title*="streamlit_calendar"]')
        expect(frame.locator(".fc-timeGridWeek-view")).to_be_visible()
        for label, css in (("Día", ".fc-timeGridDay-view .fc-timegrid-event"),
                           ("Semana", ".fc-timeGridWeek-view .fc-timegrid-event"),
                           ("Mes", ".fc-dayGridMonth-view .fc-daygrid-event")):
            page.get_by_text(label, exact=True).click()
            expect(frame.locator(css).filter(has_text="Estudio").first).to_be_visible()
            expect(frame.locator(css).filter(has_text="Transporte E2E").first).to_be_visible()
            print(f"{label}: sesiones y transporte visibles", flush=True)
        event = frame.locator(".fc-dayGridMonth-view .fc-daygrid-event").filter(has_text="Estudio").first
        event.click()
        expect(page.get_by_text("Registrar progreso", exact=True)).to_be_visible()
        frame.locator(".fc-daygrid-event").filter(has_text="Transporte E2E").first.click()
        expect(page.get_by_text("Viaje de prueba", exact=True)).to_be_visible()
        expect(page.get_by_text("17:00–18:00", exact=False).last).to_be_visible()
        page.get_by_role("combobox", name="Filtrar materias").click()
        page.get_by_role("option", name="Materia secundaria").click()
        expect(frame.locator(".fc-daygrid-event").filter(has_text="Estudio")).to_have_count(0)
        expect(frame.locator(".fc-daygrid-event").filter(has_text="Transporte E2E").first).to_be_visible()
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--ui", required=True)
    args = parser.parse_args()
    exercise(args.api, args.ui)
    print("E2E: transporte 17:00–18:00, plan 16:00–20:00 sin cruces, aprobación y eventos en tres vistas.")
