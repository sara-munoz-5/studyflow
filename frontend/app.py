import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from uuid import uuid4

import httpx
import pandas as pd
import streamlit as st
from streamlit_calendar import calendar

from calendar_view import KINDS, ZONE, block_rows, calendar_entries, day_label, intersects, local, pack_windows

API = os.getenv("STUDYFLOW_API_URL", "http://127.0.0.1:8001")
STATUS = {"pending": "Pendiente", "completed": "Completada", "cancelled": "Cancelada"}
PLAN_STATUS = {"draft": "Borrador", "approved": "Aprobado", "unavailable": "Sin disponibilidad", "superseded": "Reemplazado"}
TRACKING = {"pending": "Pendiente", "completed": "Completada", "partial": "Parcialmente completada",
            "not_done": "No realizada"}
PRIORITIES = {1: "Muy baja", 2: "Baja", 3: "Media", 4: "Alta", 5: "Crítica"}
MODES = {"agent": "Agente con Ollama", "deterministic": "Planificador sin IA"}
COVERAGE = {"scheduled": "Programado", "partial": "Parcial", "pending": "Pendiente", "historical": "Registrado"}
STAGES = {
    "get_activity_details": "Analizando la actividad",
    "get_available_slots": "Consultando disponibilidad",
    "propose_objectives": "Priorizando temas",
    "estimate_study_sessions": "Generando sesiones",
    "validate_study_plan": "Validando el plan",
    "validate_before_save": "Comprobando el calendario vigente",
    "save_plan": "Guardando el borrador",
}


def fetch(method, path, payload=None, headers=None):
    try:
        timeout = httpx.Timeout(1200 if method == "POST" and path == "/plans" else 30, connect=5)
        response = httpx.request(method, f"{API}{path}", json=payload, timeout=timeout, headers=headers)
        if response.is_error:
            detail = response.json().get("detail", "Error del servidor")
            if isinstance(detail, list):
                detail = "\n".join(f"{' / '.join(map(str, error['loc'][1:]))} · {error['msg']}" for error in detail)
            return None, str(detail)
        if path.endswith(".ics"):
            return response.content, None
        return (True if response.status_code == 204 else response.json()), None
    except httpx.RequestError:
        return None, "No se pudo conectar con StudyFlow. Comprueba la conexión con la API."
    except ValueError:
        return None, "La API devolvió una respuesta inesperada."


def request(method, path, payload=None):
    result, error = fetch(method, path, payload)
    if error:
        st.error(error)
    return result


def navigate(**state):
    st.session_state.update(state)
    st.rerun()


def save(path, record, payload, **destination):
    result = request("PUT", f"{path}/{record['id']}", payload) if record else request("POST", path, payload)
    if result:
        navigate(notice="Cambios guardados.", **destination)


def delete(path, record, related, **destination):
    st.warning(related)
    confirm = st.checkbox("Confirmo que quiero eliminar este registro", key=f"confirm-{path}-{record['id']}")
    if st.button("Confirmar eliminación", disabled=not confirm):
        if request("DELETE", f"{path}/{record['id']}"):
            navigate(notice="Registro eliminado.", **destination)


def edit_subject(record):
    st.subheader("Editar materia" if record else "Crear materia")
    with st.form("subject"):
        name = st.text_input("Nombre", record.get("name", ""), max_chars=150)
        code = st.text_input("Código", record.get("code", ""), max_chars=30)
        description = st.text_area("Descripción", record.get("description") or "", max_chars=500)
        if st.form_submit_button("Guardar materia", type="primary"):
            save("/subjects", record, {"name": name, "code": code, "description": description or None}, action=None)


def subject_cards(subjects, activities, plans):
    lead, action = st.columns([4, 1])
    lead.title("Mis materias")
    lead.caption("Actividades y planes de estudio, organizados por materia.")
    if action.button("Crear materia", type="primary", width="stretch"):
        navigate(action="create_subject")
    if not subjects:
        st.info("Crea tu primera materia para organizar actividades y planes de estudio.")
    for start in range(0, len(subjects), 3):
        for column, subject in zip(st.columns(3), subjects[start:start + 3]):
            key = subject["id"]
            ids = {item["id"] for item in activities if item["subject_id"] == key}
            count = sum(plan["activity_id"] in ids for plan in plans)
            with column.container(border=True):
                st.caption(subject["code"])
                st.subheader(subject["name"])
                if subject["description"]:
                    description = subject["description"]
                    st.write(description if len(description) <= 170 else description[:167] + "…")
                st.caption(f"{len(ids)} actividades · {count} planes")
                if st.button("Abrir materia", key=f"open-{key}", type="primary", width="stretch"):
                    navigate(subject_id=key, section="Actividades", action=None)
                edit, remove = st.columns(2)
                if edit.button("Editar", key=f"edit-{key}", width="stretch"):
                    navigate(subject_id=key, section="Información", action="edit_subject")
                if remove.button("Eliminar", key=f"remove-{key}", width="stretch"):
                    navigate(subject_id=key, section="Información", action="delete_subject")


def edit_activity(subject, record):
    today = datetime.now(ZONE).date()
    due = local(record["due_date"]) if record else datetime.combine(today + timedelta(days=1), time(18), ZONE)
    day_value = datetime.fromisoformat(record["due_day"]).date() if record.get("due_day") else due.date()
    st.subheader("Editar actividad" if record else "Crear actividad")
    with st.form("activity"):
        title = st.text_input("Título", record.get("title", ""), max_chars=150)
        kind = st.selectbox("Categoría", list(KINDS), index=list(KINDS).index(record.get("type", "exam")),
                            format_func=KINDS.get)
        left, right = st.columns(2)
        day = left.date_input("Fecha límite", day_value)
        hour = right.time_input("Hora límite", due.time())
        day_only = st.checkbox("Plazo de día completo", value=bool(record.get("due_day")),
                               help="La hora se omite del calendario. El plazo vence al terminar ese día en Bogotá.")
        rows = record.get("topic_details") or [
            {"name": topic, "id": record.get("topic_ids", {}).get(topic), "priority": 3, "mastery": None}
            for topic in record.get("topics", [])
        ]
        st.markdown("**Temas de estudio**")
        st.caption("Prioridad · 1 Muy baja · 2 Baja · 3 Media · 4 Alta · 5 Crítica")
        st.caption("Dominio (opcional) · 1 Inicial a 5 Avanzado")
        table = pd.DataFrame(rows, columns=["id", "name", "priority", "mastery"])
        table["name"] = table["name"].astype("string")
        table["priority"] = table["priority"].astype("Int64")
        table["mastery"] = table["mastery"].astype("Int64")
        edited = st.data_editor(table, num_rows="dynamic", hide_index=True, width="stretch",
                                column_config={
                                    "id": None,
                                    "name": st.column_config.TextColumn("Tema", required=True, max_chars=120),
                                    "priority": st.column_config.NumberColumn("Prioridad", min_value=1, max_value=5,
                                                                              step=1, default=3, required=True),
                                    "mastery": st.column_config.NumberColumn("Dominio", min_value=1, max_value=5, step=1),
                                }, key=f"topics-{record.get('id', 'new')}")
        left, right = st.columns(2)
        difficulty = left.slider("Dificultad", 1, 5, record.get("difficulty", 3))
        priority = right.slider("Prioridad", 1, 5, record.get("priority", 3))
        st.caption("El agente estima el tiempo al generar el plan. Puedes ajustar la sugerencia desde el borrador.")
        legacy_hours = record.get("estimated_hours")
        if legacy_hours and st.checkbox("Usar una nueva estimación al generar el siguiente plan"):
            legacy_hours = None
        status = st.selectbox("Estado", list(STATUS), index=list(STATUS).index(record.get("status", "pending")),
                              format_func=STATUS.get)
        if st.form_submit_button("Guardar actividad", type="primary"):
            details = []
            for row in edited.to_dict("records"):
                if pd.isna(row["name"]) or not row["name"].strip():
                    continue
                details.append({"id": None if pd.isna(row["id"]) else row["id"], "name": row["name"].strip(),
                                "priority": 3 if pd.isna(row["priority"]) else int(row["priority"]),
                                "mastery": None if pd.isna(row["mastery"]) else int(row["mastery"])})
            if not details:
                st.error("Agrega al menos un tema en la tabla.")
                return
            names = {item["name"] for item in details}
            save("/activities", record, {
                "subject_id": subject["id"], "title": title, "type": kind,
                "due_date": datetime.combine(day, hour, ZONE).isoformat(), "due_day": day.isoformat() if day_only else None,
                "difficulty": difficulty, "topic_details": details,
                "topic_weights": {name: value for name, value in record.get("topic_weights", {}).items() if name in names},
                "status": status, "priority": priority, "estimated_hours": legacy_hours,
            }, action=None)


def deadline_label(activity):
    if activity.get("due_day"):
        day = datetime.fromisoformat(activity["due_day"]).date()
        return f"{day_label(day)} · Día completo"
    due = local(activity["due_date"])
    return f"{day_label(due.date())} · {due:%H:%M}"


def show_session(session, subject, activity, plan=None):
    start, end = local(session["start"]), local(session["end"])
    state = TRACKING[session.get("study_status", "pending")]
    if session["status"] == "proposed":
        state = "Propuesta"
    elif session["status"] == "replaced" and not session.get("effective_minutes"):
        state = "Reemplazada"
    with st.container(border=True):
        end_label = end.strftime("%H:%M") if start.date() == end.date() else end.strftime("%d/%m %H:%M")
        st.caption(f"{start:%H:%M}–{end_label} · {session['duration_minutes']} min · {state}")
        st.subheader(session["topic"])
        st.caption(f"{subject['name']} · {activity['title']}")
        st.write(session["objective"])
        if session.get("effective_minutes"):
            st.caption(f"{session['effective_minutes']} minutos efectivos")
        if plan and plan["status"] == "approved":
            with st.expander("Registrar progreso"):
                update_tracking(plan, session)
        if session.get("tracking_history"):
            with st.expander("Historial de seguimiento"):
                for entry in reversed(session["tracking_history"]):
                    st.write(f"{local(entry['at']):%d/%m/%Y %H:%M} · {TRACKING[entry['after']['status']]} · "
                             f"{entry['after']['minutes']} min")


def update_tracking(plan, session):
    key = session['id']
    options = list(TRACKING)
    state = st.selectbox("Estado de estudio", options, index=options.index(session.get("study_status", "pending")),
                         format_func=TRACKING.get, key=f"tracking-{key}")
    minutes = None
    if state == "partial":
        if session["duration_minutes"] <= 1:
            st.info("Una sesión de un minuto solo admite progreso pendiente, completado o no realizado.")
            return
        maximum = session["duration_minutes"] - 1
        minutes = st.number_input("Minutos efectivos", min_value=1, max_value=maximum,
                                  value=min(maximum, max(1, session.get("effective_minutes", 0))),
                                  step=1, key=f"minutes-{key}")
    if st.button("Guardar progreso", key=f"save-tracking-{key}"):
        if request("PATCH", f"/plans/{plan['id']}/sessions/{key}/tracking",
                   {"status": state, "effective_minutes": minutes}):
            navigate(notice="Progreso actualizado.")


def start_config(activity_id, previous=None):
    navigate(action="generate", activity_id=activity_id, previous=previous,
             configuration=uuid4().hex, occupied_initialized=False)


def show_plan(plan, subject, activity):
    st.subheader(activity["title"])
    st.caption(f"{PLAN_STATUS[plan['status']]} · {MODES[plan['mode']]}")
    planned, required = plan["planned_minutes"], plan["required_minutes"]
    coverage = plan["coverage"]
    percent = planned / required if required else 0
    labels = [("Requerido", f"{required} min"), ("Planificado", f"{planned} min"),
              ("Pendiente", f"{plan['missing_minutes']} min"), ("Cobertura", f"{percent:.0%}")]
    for column, (label, value) in zip(st.columns(4), labels):
        column.metric(label, value)
    st.progress(percent)
    if plan.get("replaces_plan_id"):
        st.info(f"Reemplazo del plan #{plan['replaces_plan_id']}. El cambio de reservas se aplica al aceptar.")
    if plan.get("proposed_due_date"):
        st.write(f"Nuevo plazo propuesto · {local(plan['proposed_due_date']):%d/%m/%Y %H:%M}")
    if plan["status"] in {"approved", "superseded"}:
        effective = plan.get("completed_minutes", 0)
        st.progress(min(1.0, effective / required) if required else 0.0,
                    text=f"Estudio registrado · {effective} de {required} min")
    if plan["reasons"]:
        st.warning(" ".join(plan["reasons"]))
    if plan["status"] == "draft":
        left, right = st.columns(2)
        if left.button("Aceptar plan", type="primary", width="stretch"):
            if request("POST", f"/plans/{plan['id']}/approve"):
                navigate(notice="Plan aprobado. Sus sesiones ya aparecen en Mi calendario.")
        if right.button("Modificar o regenerar", width="stretch"):
            start_config(activity["id"], plan)
    elif plan["status"] == "unavailable" and st.button("Modificar disponibilidad", type="primary"):
        start_config(activity["id"], plan)
    if plan["status"] == "approved":
        if st.button("Replanificar tiempo restante", type="primary"):
            start_config(activity["id"], plan)
        export_button(plan["id"], f"plan-{plan['id']}")
    if plan["sessions"]:
        days = defaultdict(list)
        for item in plan["sessions"]:
            days[local(item["start"]).date()].append(item)
        for day, items in sorted(days.items()):
            st.markdown(f"#### {day_label(day)}")
            for item in items:
                show_session(item, subject, activity, plan)
    with st.expander("Cobertura por tema", expanded=True):
        counts = {status: sum(item["status"] == status for item in coverage) for status in COVERAGE}
        summary = (f"{len(plan['sessions'])} sesiones · {counts['scheduled']} temas completos "
                   f"· {counts['partial']} parciales · {counts['pending']} pendientes")
        if counts["historical"]:
            summary += f" · {counts['historical']} registrados sin cuota histórica"
        st.caption(summary)
        if plan["created_at"] is None:
            st.caption("Historial anterior. Se muestran los minutos registrados y los temas conocidos; la cuota original está sin registrar.")
        for item in coverage:
            minutes = f"{item['planned_minutes']} de {item['required_minutes']} min" if item["required_minutes"] is not None else f"{item['planned_minutes']} min"
            st.write(f"{item['topic']} · {COVERAGE[item['status']]} · {minutes}")
            if item.get("objective"):
                st.caption(item["objective"])
            if item["status"] in {"partial", "pending"} and plan["reasons"]:
                st.caption(plan["reasons"][0])
    with st.expander("¿Por qué la IA creó este plan?" if plan["mode"] == "agent" else "Cómo se creó el plan"):
        if plan["mode"] == "agent":
            st.write("Ollama propone los objetivos y el orden pedagógico. La prioridad declarada por el estudiante precede a la sugerida.")
        else:
            st.write("El planificador sin IA utiliza prioridades declaradas y reglas de esfuerzo.")
        suggested = sum(item.get("suggested_minutes") or 0 for item in coverage)
        if suggested:
            st.write(f"Estimación propuesta · {suggested} min")
        for item in coverage:
            priority = item.get("priority")
            if priority is not None or item.get("rationale"):
                st.write(f"{item['topic']} · {PRIORITIES.get(priority, 'Prioridad sin registrar')}")
            if item.get("rationale"):
                st.caption(item["rationale"])
        for assumption in plan.get("assumptions", []):
            st.caption(assumption)
        st.write("El backend distribuye las cuotas entre ventanas libres y valida fechas, duración y conflictos.")
        for reason in plan["reasons"]:
            st.caption(reason)
    if plan["tools_used"]:
        with st.expander("Pasos ejecutados por el agente"):
            for step in plan["tools_used"]:
                st.write(STAGES.get(step, step))


def export_button(plan_id, key):
    if st.button("Preparar archivo .ics", key=f"prepare-{key}"):
        st.session_state[f"ics-{plan_id}"] = request("GET", f"/plans/{plan_id}/calendar.ics")
    if document := st.session_state.get(f"ics-{plan_id}"):
        st.download_button("Descargar .ics", document, f"studyflow-{plan_id}.ics", "text/calendar", key=f"download-{key}")


@st.cache_resource
def generator_pool():
    return ThreadPoolExecutor(max_workers=4, thread_name_prefix="studyflow-generator")


@st.fragment(run_every=1)
def generation_progress():
    job = st.session_state.job
    if job["future"].done():
        result, error = job["future"].result()
        del st.session_state.job
        if error:
            navigate(generation_error=error)
        navigate(action="show_plan", section="Planes de estudio", navigation="Mis materias",
                 selected_plan=result["id"], transient=result)
    st.subheader("Generando el borrador")
    progress, _ = fetch("GET", f"/plans/progress/{job['id']}")
    latest = {item["step"]: item["outcome"] for item in (progress or {}).get("events", [])}
    visible = [(STAGES[step], status) for step, status in latest.items() if step in STAGES]
    if not visible:
        st.caption("Esperando la respuesta del backend…")
    for label, status in visible:
        st.write(f"{'✓' if status == 'ok' else '…' if status == 'running' else '!' } {label}")


def availability_form(activity, plans):
    st.subheader("Disponibilidad para estudiar")
    st.caption(f"{activity['title']} · {deadline_label(activity)} · America/Bogota")
    config = st.session_state.configuration
    previous = st.session_state.previous or {}
    source_id = previous.get("replaces_plan_id") or (previous.get("id") if previous.get("status") == "approved" else None)
    target_minutes = proposed_due_date = None
    if source_id:
        st.info("Las reservas del plan anterior se conservan hasta que aceptes el reemplazo.")
        if st.checkbox("Proponer un nuevo plazo", value=bool(previous.get("proposed_due_date")), key=f"change-due-{config}"):
            deadline = local(previous.get("proposed_due_date") or activity["due_date"])
            date_col, time_col = st.columns(2)
            new_day = date_col.date_input("Nueva fecha límite", deadline.date(), key=f"new-date-{config}")
            new_hour = time_col.time_input("Nueva hora límite", deadline.time(), key=f"new-time-{config}")
            proposed_due_date = datetime.combine(new_day, new_hour, ZONE).isoformat()
    elif previous.get("required_minutes") is not None:
        if st.checkbox("Ajustar el tiempo requerido", value=previous.get("estimate_source") == "adjusted",
                       key=f"override-{config}"):
            target_minutes = st.number_input("Tiempo total (minutos)", min_value=len(activity["topics"]),
                                             max_value=12000, value=min(12000, previous["required_minutes"]),
                                             step=5, key=f"target-{config}")
    today = datetime.now(ZONE).date()
    default_first = local(previous["availability"][0]["start"]) if previous.get("availability") else datetime.combine(today, time(17), ZONE)
    default_last = local(previous["availability"][-1]["end"]) if previous.get("availability") else datetime.combine(today + timedelta(days=3), time(20), ZONE)
    mode = st.radio("Modo", list(MODES), index=list(MODES).index(previous.get("mode", "agent")),
                    format_func=MODES.get, horizontal=True, key=f"mode-{config}")
    period = st.date_input("Días disponibles", (default_first.date(), default_last.date()), key=f"days-{config}")
    a, b = st.columns(2)
    start = a.time_input("Inicio diario", default_first.time(), step=timedelta(minutes=30), key=f"start-{config}")
    end = b.time_input("Fin diario", default_last.time(), step=timedelta(minutes=30), key=f"end-{config}")
    limit = st.slider("Máximo por sesión (minutos)", 15, 120, previous.get("max_session_minutes", 60), key=f"limit-{config}")
    if len(period) != 2 or start >= end or (period[1] - period[0]).days >= 100:
        st.info("Selecciona un intervalo de hasta 100 días y un inicio anterior al fin.")
        return
    availability = [(datetime.combine(period[0] + timedelta(days=i), start, ZONE),
                     datetime.combine(period[0] + timedelta(days=i), end, ZONE))
                    for i in range((period[1] - period[0]).days + 1)]
    reserved = [(local(session["start"]), local(session["end"])) for plan in plans if plan["status"] == "approved"
                for session in plan["sessions"]
                if plan["id"] != source_id or session.get("study_status") == "completed"]
    if not st.session_state.occupied_initialized:
        original = [(local(item["start"]), local(item["end"])) for item in previous.get("busy", [])]
        st.session_state.occupied = {slot for window in availability for slot in block_rows(*window)
                                     if any(intersects(*slot, *busy) for busy in original)}
        st.session_state.occupied_initialized = True

    st.caption("□ Libre · ☑ Ocupado por ti · 🔒 Incluye una sesión aprobada · — Fuera de plazo")
    if st.button("Limpiar selección"):
        for key in list(st.session_state):
            if key.startswith(f"cell-{config}-"):
                del st.session_state[key]
        navigate(occupied=set())
    week = st.selectbox("Fechas visibles", range(0, len(availability), 4),
                        format_func=lambda offset: f"{day_label(availability[offset][0].date())} – "
                                                   f"{day_label(availability[min(offset + 3, len(availability)-1)][0].date())}",
                        key=f"page-{config}")
    shown = availability[week:week + 4]
    columns = st.columns([1, *([1.3] * len(shown))])
    for column, window in zip(columns[1:], shown):
        column.caption(day_label(window[0].date()))
    deadline, now = local(proposed_due_date or activity["due_date"]), datetime.now(ZONE)
    for slots in zip(*(block_rows(*window) for window in shown)):
        columns[0].caption(f"{slots[0][0]:%H:%M}–{slots[0][1]:%H:%M}")
        for column, slot in zip(columns[1:], slots):
            blocked = any(intersects(*slot, *item) for item in reserved)
            expired = slot[1] <= now or slot[0] >= deadline
            if blocked or expired:
                column.write("🔒" if blocked else "—")
                continue
            checked = column.checkbox(f"{slot[0]:%d/%m %H:%M}", value=slot in st.session_state.occupied,
                                      key=f"cell-{config}-{slot[0].isoformat()}-{slot[1].isoformat()}",
                                      label_visibility="collapsed")
            if checked:
                st.session_state.occupied.add(slot)
            else:
                st.session_state.occupied.discard(slot)
    if error := st.session_state.pop("generation_error", None):
        st.error(error)
    if st.button("Generar borrador", type="primary"):
        manual = pack_windows(slot for slot in st.session_state.occupied if any(
            left <= slot[0] < slot[1] <= right for left, right in availability
        ))
        job_id = str(uuid4())
        payload = {"activity_id": activity["id"], "timezone": ZONE.key, "mode": mode,
                   "availability": pack_windows(availability), "busy": manual, "max_session_minutes": limit,
                   "target_minutes": target_minutes, "replaces_plan_id": source_id, "proposed_due_date": proposed_due_date}
        future = generator_pool().submit(fetch, "POST", "/plans", payload, {"X-Plan-Progress": job_id})
        navigate(job={"id": job_id, "future": future}, previous={**previous, **payload})


def subject_detail(subject, records, plans):
    if st.button("← Mis materias"):
        navigate(subject_id=None, action=None)
    st.title(subject["name"])
    st.caption(subject["code"])
    sections = ["Actividades", "Planes de estudio", "Información"]
    section = st.segmented_control("Sección", sections, default=st.session_state.section,
                                   label_visibility="collapsed", key=f"section-{subject['id']}-{st.session_state.section}")
    if section != st.session_state.section and section is not None:
        navigate(section=section, action=None)
    action = st.session_state.action
    activities = {item["id"]: item for item in records if item["subject_id"] == subject["id"]}
    history = [plan for plan in plans if plan["activity_id"] in activities]
    current = activities.get(st.session_state.get("activity_id"))
    if section == "Información":
        if action == "edit_subject":
            edit_subject(subject)
        elif action == "delete_subject":
            delete("/subjects", subject,
                   "Se elimina únicamente una materia sin actividades. Las actividades y los planes asociados se conservan.",
                   subject_id=None, action=None)
        else:
            st.write(subject["description"] or "Sin descripción")
            left, right = st.columns(2)
            if left.button("Editar materia"):
                navigate(action="edit_subject")
            if right.button("Eliminar materia"):
                navigate(action="delete_subject")
        return
    if action == "generate" and current:
        if st.button("Volver a la materia"):
            navigate(action=None)
        availability_form(current, plans)
        return
    if section == "Planes de estudio":
        if action == "show_plan":
            selected = next((plan for plan in history if plan["id"] == st.session_state.selected_plan), None)
            if selected is None:
                selected = st.session_state.get("transient")
            if selected and selected["activity_id"] in activities:
                if st.button("Volver al historial"):
                    navigate(action=None)
                show_plan(selected, subject, activities[selected["activity_id"]])
                return
        if not history:
            st.info("Los borradores y planes aprobados aparecerán aquí.")
        for plan in history:
            with st.container(border=True):
                st.subheader(activities[plan["activity_id"]]["title"])
                created = local(plan["created_at"]).strftime("%d/%m/%Y %H:%M") if plan["created_at"] else "Fecha sin registrar"
                st.caption(f"{PLAN_STATUS[plan['status']]} · {created}")
                st.write(f"{plan['planned_minutes']} min planificados · {plan['missing_minutes']} min pendientes")
                if st.button("Abrir plan", key=f"plan-{plan['id']}"):
                    navigate(action="show_plan", selected_plan=plan["id"], transient=None)
        return
    if action in {"create_activity", "edit_activity", "delete_activity"}:
        if st.button("Volver a actividades"):
            navigate(action=None)
        if action == "delete_activity" and current:
            delete("/activities", current, "Se elimina únicamente una actividad sin planes. El historial se conserva.", action=None)
        else:
            edit_activity(subject, current if action == "edit_activity" and current else {})
        return
    if st.button("Crear actividad", type="primary"):
        navigate(action="create_activity")
    if not activities:
        st.info("Registra una actividad para preparar tu primer plan.")
    for item in activities.values():
        key = item["id"]
        with st.container(border=True):
            st.caption(f"{KINDS[item['type']]} · {STATUS[item['status']]}")
            st.subheader(item["title"])
            st.write(deadline_label(item))
            with st.expander("Detalles de la actividad"):
                credits = sum(plan.get("completed_minutes", 0) for plan in history
                              if plan["activity_id"] == key and plan["status"] in {"approved", "superseded"})
                st.caption(f"Dificultad {item['difficulty']}/5 · Prioridad {item['priority']}/5 · {credits} min estudiados")
                for topic in item.get("topic_details") or [{"name": name, "priority": 3, "mastery": None} for name in item["topics"]]:
                    mastery = f" · Dominio {topic['mastery']}/5" if topic["mastery"] else ""
                    st.write(f"{topic['name']} · {PRIORITIES[topic['priority']]}{mastery}")
            generate, edit, remove = st.columns([2, 1, 1])
            if generate.button("Generar plan", key=f"generate-{key}", disabled=item["status"] != "pending"):
                start_config(key)
            if edit.button("Editar", key=f"activity-edit-{key}"):
                navigate(action="edit_activity", activity_id=key)
            if remove.button("Eliminar", key=f"activity-delete-{key}"):
                navigate(action="delete_activity", activity_id=key)


def calendar_page(subjects, activities, plans):
    st.title("Mi calendario")
    st.caption("America/Bogota · Los bloques Estudio corresponden a sesiones aprobadas.")
    filters = st.multiselect("Filtrar materias", [item["id"] for item in subjects],
                             format_func={item["id"]: item["name"] for item in subjects}.get)
    if filters:
        activities = [item for item in activities if item["subject_id"] in filters]
        ids = {item["id"] for item in activities}
        plans = [plan for plan in plans if plan["activity_id"] in ids]
    st.markdown(" · ".join(
        f":{color}[{KINDS[key]}]" for key, color in (("exam", "red"), ("assignment", "blue"),
                                                    ("laboratory", "violet"), ("project", "orange"))
    ))
    events, details = calendar_entries(subjects, activities, plans)
    selection = st.container()
    result = calendar(events=events, options={
        "initialView": "timeGridWeek", "initialDate": datetime.now(ZONE).date().isoformat(),
        "firstDay": 1, "timeZone": "UTC", "locale": "es", "height": "auto", "scrollTime": "08:00:00",
        "headerToolbar": {"left": "prev,next today", "center": "title", "right": "timeGridDay,timeGridWeek,dayGridMonth"},
        "buttonText": {"today": "Hoy", "day": "Día", "week": "Semana", "month": "Mes"},
        "eventTimeFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False},
        "slotLabelFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False},
        "slotDuration": "00:30:00", "dayMaxEvents": True, "editable": False,
    }, callbacks=["eventClick"], custom_css=".fc-event-title { white-space: normal; } .fc .fc-toolbar { flex-wrap: wrap; gap: .6rem; }",
                      key="study-calendar") or {}
    clicked = result.get("eventClick", {}).get("event", {}).get("id")
    if clicked in details and result.get("callback") == "eventClick":
        item = details[clicked]
        if item["session"]:
            with selection:
                st.caption(day_label(local(item['session']['start']).date()))
                show_session(item["session"], item["subject"], item["activity"], item["plan"])
                if item["plan"]["status"] == "approved":
                    export_button(item["plan"]["id"], "calendar-event")
        else:
            with selection.container(border=True):
                st.subheader(item["activity"]["title"])
                st.caption(f"{item['subject']['name']} · {KINDS[item['activity']['type']]}")
                st.write(deadline_label(item["activity"]))


def main():
    st.set_page_config(page_title="StudyFlow AI", layout="wide")
    st.html("""<style>
    .stMainBlockContainer { max-width: 78rem; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: #fff; border-radius: 1rem; border-color: #dce6ee;
    }
    [data-testid="stSidebar"] { border-right: 1px solid #dce6ee; }
    h1, h2, h3 { letter-spacing: -0.025em; }
    </style>""")
    st.session_state.setdefault("subject_id", None)
    st.session_state.setdefault("section", "Actividades")
    st.session_state.setdefault("action", None)
    st.sidebar.title("StudyFlow AI")
    if st.session_state.get("job"):
        generation_progress()
        return
    page = st.sidebar.radio("Navegación", ["Mis materias", "Mi calendario"], label_visibility="collapsed",
                            key="navigation")
    if notice := st.session_state.pop("notice", None):
        st.success(notice)
    subjects = request("GET", "/subjects")
    activities = request("GET", "/activities")
    plans = request("GET", "/plans")
    if any(items is None for items in (subjects, activities, plans)):
        return
    if page == "Mi calendario":
        calendar_page(subjects, activities, plans)
        return
    if st.session_state.action == "create_subject":
        if st.button("← Mis materias"):
            navigate(action=None)
        edit_subject({})
        return
    subject = next((item for item in subjects if item["id"] == st.session_state.subject_id), None)
    if subject:
        subject_detail(subject, activities, plans)
    else:
        subject_cards(subjects, activities, plans)


if __name__ == "__main__":
    main()
