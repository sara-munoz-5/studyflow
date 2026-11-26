import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.academic.application.activities import ActivityService
from app.academic.domain.entities import AcademicActivity, ActivityStatus, Subject
from app.core.telemetry import PlanTrace

from ..domain.entities import StudyPlan, TopicCoverage, Window
from ..domain.repositories import PlanRepository
from ..domain.scheduler import allocate, free_slots, merge, rough_effort, topic_quotas, violations


REVIEW_MARGIN = timedelta(minutes=5)


PlanningAgent = Callable[
    [AcademicActivity, Callable[[], Subject], Callable[[], list[Window]], int, PlanTrace],
    tuple[dict[str, str], list[str], dict[str, int], dict[str, tuple[int, str]]],
]


class PlanConflict(Exception):
    pass


class PlanNotFound(Exception):
    pass


def explain_shortage(availability, busy, reserved, now, deadline) -> list[str]:
    def minutes(windows):
        return sum(int((window.end - window.start).total_seconds() // 60) for window in windows)

    before = minutes(free_slots(availability, [], now, deadline))
    after_manual = minutes(free_slots(availability, busy, now, deadline))
    free = minutes(free_slots(availability, busy + reserved, now, deadline))
    reasons = [f"Quedaron {free} minutos libres dentro del horario seleccionado antes del plazo."]
    if any(window.end > deadline for window in merge(availability)):
        reasons.append("El plazo de la actividad recortó el horario seleccionado.")
    if any(window.start < now for window in availability):
        reasons.append("Se excluyó el tiempo que ya había transcurrido.")
    if before > after_manual:
        reasons.append(f"Los bloques ocupados quitaron {before - after_manual} minutos.")
    if after_manual > free:
        reasons.append(f"Las sesiones de planes aprobados reservaron {after_manual - free} minutos adicionales.")
    return reasons


def version_of(plan: StudyPlan, activity: AcademicActivity) -> str:
    detail = [activity.due_date.isoformat(), activity.due_day, activity.structured_topics,
              activity.difficulty, activity.topic_weights,
              [(item.id, item.study_status, item.effective_minutes) for item in plan.sessions]]
    return hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()


def remaining_quotas(source: StudyPlan, activity: AcademicActivity, objectives: dict[str, str]) -> dict[str, int]:
    recorded = {item.topic: item for item in source.coverage}
    by_id = {item.topic_id: item for item in source.coverage}
    credit = Counter()
    for session in source.sessions:
        if item := recorded.get(session.topic):
            credit[item.topic_id] += session.effective_minutes
    old_total = max(len(objectives), source.required_minutes)
    legacy = topic_quotas(activity, objectives, total_minutes=old_total)
    fallback = rough_effort(activity)
    result = {}
    for topic, identifier in activity.topic_ids.items():
        if item := by_id.get(identifier):
            required = item.required_minutes if item.required_minutes is not None else legacy[topic]
            result[topic] = max(0, required - credit[identifier])
        else:
            result[topic] = fallback[topic]
    return {topic: result[topic] for topic in objectives}


class PlanService:
    def __init__(self, repository: PlanRepository, activities: ActivityService):
        self.repository = repository
        self.activities = activities

    def get(self, plan_id: int) -> StudyPlan:
        plan = self.repository.get(plan_id)
        if plan is None:
            raise PlanNotFound("Plan no encontrado")
        plan.restore_legacy_coverage(self.activities.get_by_id(plan.activity_id).topics)
        return plan

    def list_all(self) -> list[StudyPlan]:
        topics = {activity.id: activity.topics for activity in self.activities.get_all()}
        plans = self.repository.list_all()
        for plan in plans:
            plan.restore_legacy_coverage(topics.get(plan.activity_id, []))
        return plans

    def generate(
        self, activity_id: int, timezone_name: str, availability: list[Window],
        busy: list[Window], limit: int, mode: str,
        agent: PlanningAgent, observer: Callable[[dict], None] | None = None,
        target_minutes: int | None = None, replaces_plan_id: int | None = None,
        proposed_due_date: datetime | None = None,
    ) -> StudyPlan:
        activity = self.activities.get_by_id(activity_id)
        if activity.status != ActivityStatus.PENDING:
            raise PlanConflict("La actividad debe estar pendiente")
        source = self._replacement(replaces_plan_id, activity_id)
        version = version_of(source, activity) if source else None
        if proposed_due_date is not None and source is None:
            raise PlanConflict("El cambio de plazo requiere reemplazar un plan aprobado")
        if target_minutes is not None and (source or target_minutes < len(activity.topics)):
            raise PlanConflict("El ajuste debe cubrir al menos un minuto por tema y se aplica a planes iniciales")
        effective = replace(activity, due_date=proposed_due_date or activity.due_date)
        trace = PlanTrace(activity_id, observer)
        tools = []
        weights = None
        estimates = {}
        assumptions = []
        estimate_source = "manual" if activity.estimated_hours is not None else "deterministic"
        if mode == "agent":
            def load_subject():
                subject = self.activities.subjects.get_by_id(activity.subject_id)
                if subject is None:
                    raise PlanConflict("La materia cambió durante la generación")
                return subject

            def load_slots():
                now = datetime.now(timezone.utc)
                return free_slots(availability, busy + self.repository.busy(now, replaces_plan_id), now, effective.due_date)

            with trace.step("run_agent"):
                # A replacement reuses historical effort and asks the model for study objectives only.
                context = replace(effective, estimated_hours=source.required_minutes / 60) if source else effective
                objectives, tools, weights, estimates = agent(context, load_subject, load_slots, limit, trace)
        else:
            ordered = sorted(activity.structured_topics, key=lambda item: item["priority"], reverse=True)
            objectives = {item["name"]: f"Resolver ejercicios y explicar los conceptos de {item['name']}" for item in ordered}

        if estimates:
            estimate_source = "agent"
        elif activity.estimated_hours is None and source is None:
            estimates = {topic: (minutes, "Referencia según dificultad y dominio declarado.")
                         for topic, minutes in rough_effort(activity).items()}
        if source:
            quotas = remaining_quotas(source, activity, objectives)
            estimate_source = "remaining"
            previous = {item.topic_id: item for item in source.coverage}
            for topic, identifier in activity.topic_ids.items():
                item = previous.get(identifier)
                if item and item.suggested_minutes is not None:
                    estimates[topic] = (item.suggested_minutes, item.rationale)
            if any(item.required_minutes is None for item in source.coverage):
                assumptions.append("Las cuotas del historial previo se reconstruyeron a partir del esfuerzo total.")
        elif target_minutes is not None:
            quotas = topic_quotas(activity, objectives, {topic: item[0] for topic, item in estimates.items()} or weights,
                                 total_minutes=target_minutes)
            estimate_source = "adjusted"
        elif estimates:
            quotas = {topic: estimates[topic][0] for topic in objectives}
        else:
            quotas = topic_quotas(activity, objectives, weights)
        if estimates or (activity.estimated_hours is None and source is None):
            assumptions.append("El esfuerzo sugerido es aproximado y se estima independientemente del horario libre.")
            if any(item["mastery"] is None for item in activity.structured_topics):
                assumptions.append("Se tomó dominio intermedio como referencia cuando el nivel no se declaró.")

        # Recheck after inference in case time elapsed or another request approved a plan.
        with self.repository.serialized():
            with trace.step("validate_before_save", mode=mode) as result:
                current = self.activities.get_by_id(activity_id)
                if current != activity:
                    raise PlanConflict("La actividad cambió durante la generación")
                now = datetime.now(timezone.utc)
                next_second = now.replace(microsecond=0) + timedelta(seconds=1)
                fresh_source = self._replacement(replaces_plan_id, activity_id)
                if fresh_source and version_of(fresh_source, current) != version:
                    raise PlanConflict("Cambió el progreso del plan original. Genera otra propuesta")
                reserved = self.repository.busy(now, replaces_plan_id)
                review_start = next_second + REVIEW_MARGIN
                review_windows = [
                    Window(review_start, window.end) if window.start < next_second else window
                    for window in availability if window.start >= next_second or window.end > review_start
                ]
                slots = free_slots(review_windows, busy + reserved, next_second, effective.due_date)
                sessions = allocate(effective, slots, limit, objectives, weights, quotas)
                errors = violations(sessions, slots, effective, limit)
                result.update(session_count=len(sessions), violation_count=len(errors))
                if errors:
                    raise PlanConflict("; ".join(errors))
            missing = max(0, sum(quotas.values()) - sum(item.duration_minutes for item in sessions))
            reasons = explain_shortage(review_windows, busy, reserved, next_second, effective.due_date) if missing else []
            if missing and any(window.end <= next_second for window in availability):
                reasons.append("Algunas ventanas seleccionadas ya habían terminado.")
            if missing and any(window.start < next_second < window.end for window in availability):
                reasons.append("Las ventanas en curso dejan hasta cinco minutos para revisar el borrador.")
            totals = Counter()
            for session in sessions:
                totals[session.topic] += session.duration_minutes
            ids = current.topic_ids
            priorities = {item["name"]: item["priority"] for item in current.structured_topics}
            coverage = [TopicCoverage(ids[topic], topic, quotas[topic], totals[topic], objectives[topic],
                                      *estimates.get(topic, (None, None)), priorities[topic])
                        for topic in objectives]
            if source and not sum(quotas.values()):
                reasons = ["El plan original ya completó el esfuerzo requerido."]
            # A plan always contains at least one session. An empty result can still report viability.
            plan = StudyPlan(activity_id, timezone_name, mode, availability, busy, limit,
                             sessions, missing, reasons, tools_used=tools, created_at=now, coverage=coverage,
                             estimate_source=estimate_source, assumptions=assumptions,
                             replaces_plan_id=replaces_plan_id, replacement_version=version,
                             proposed_due_date=proposed_due_date)
            with trace.step("save_plan") as result:
                if not sessions:
                    plan.status = "unavailable"
                    if not estimates or source:
                        result["saved"] = False
                        return plan
                saved = self.repository.save(plan)
                result["saved"] = True
                return saved

    def _replacement(self, identifier: int | None, activity_id: int) -> StudyPlan | None:
        if identifier is None:
            return None
        source = self.get(identifier)
        if source.activity_id != activity_id or source.status != "approved":
            raise PlanConflict("El plan original debe seguir aprobado y pertenecer a la actividad")
        return source

    def track(self, plan_id: int, session_id: int, status: str, minutes: int | None) -> StudyPlan:
        with self.repository.serialized():
            plan = self.get(plan_id)
            session = next((item for item in plan.sessions if item.id == session_id), None)
            if session is None:
                raise PlanNotFound("Sesión no encontrada")
            if plan.status != "approved" or session.status != "scheduled":
                raise PlanConflict("El seguimiento se puede modificar en sesiones del plan aprobado vigente")
            if status == "partial":
                if minutes is None or not 0 < minutes < session.duration_minutes:
                    raise PlanConflict("Los minutos efectivos deben estar entre 1 y la duración menos un minuto")
                effective = minutes
            else:
                effective = session.duration_minutes if status == "completed" else 0
                if minutes is not None and minutes != effective:
                    raise PlanConflict("Los minutos efectivos deben corresponder al estado")
            self.repository.track(session.id, status, effective, datetime.now(timezone.utc))
            return self.get(plan_id)

    def approve(self, plan_id: int) -> StudyPlan:
        with self.repository.serialized():
            plan = self.get(plan_id)
            if plan.status == "approved":
                return plan
            if plan.status != "draft":
                raise PlanConflict("Solo se pueden aprobar borradores")
            activity = self.activities.get_by_id(plan.activity_id)
            source = self._replacement(plan.replaces_plan_id, activity.id)
            if source and version_of(source, activity) != plan.replacement_version:
                raise PlanConflict("El progreso o el plazo del plan original cambió. Regenera el borrador")
            now = datetime.now(timezone.utc)
            deadline = plan.proposed_due_date or activity.due_date
            effective = replace(activity, due_date=deadline)
            slots = free_slots(plan.availability, plan.busy + self.repository.busy(now, plan.replaces_plan_id), now, deadline)
            errors = violations(plan.sessions, slots, effective, plan.max_session_minutes)
            if any(session.start < now for session in plan.sessions):
                errors.insert(0, "Una sesión del borrador ya empezó. Usa Modificar o regenerar para actualizar sus horarios")
            if plan.proposed_due_date and any(
                other.id != plan.replaces_plan_id and other.activity_id == activity.id and other.status == "approved"
                and any(session.end > max(now, deadline) for session in other.sessions)
                for other in self.repository.list_all()
            ):
                errors.append("Otro plan aprobado de la actividad queda fuera del nuevo plazo")
            if activity.status != ActivityStatus.PENDING:
                errors.append("La actividad debe estar pendiente")
            if errors:
                raise PlanConflict("; ".join(errors))
            approved = self.repository.approve(plan, now)
            approved.restore_legacy_coverage(activity.topics)
            return approved
