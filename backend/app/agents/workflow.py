import json
import os
from collections.abc import Callable
from typing import TypedDict

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_ollama import ChatOllama
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from ollama import ResponseError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from app.academic.domain.entities import AcademicActivity, Subject
from app.core.telemetry import PlanTrace
from app.planning.domain.entities import StudySession, Window
from app.planning.domain.scheduler import allocate, violations

MAX_PROPOSALS = 2
OPERATIONS = (
    "get_activity_details",
    "get_available_slots",
    "estimate_study_sessions",
    "validate_study_plan",
)


class AgentUnavailable(Exception):
    pass


class AgentFailure(Exception):
    pass


class RankedObjective(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    objective: str = Field(min_length=5, max_length=300)
    study_priority: int = Field(strict=True, ge=1, le=5)


class EstimatedObjective(RankedObjective):
    required_minutes: int = Field(strict=True, ge=5, le=480)
    rationale: str = Field(min_length=5, max_length=220)


class ObjectiveProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def for_topics(self, topics: list[str]) -> tuple[dict[str, str], dict[str, int]]:
        ranked = [(topic, getattr(self, f"topic_{index}")) for index, topic in enumerate(topics, 1)]
        ranked.sort(key=lambda item: item[1].study_priority, reverse=True)
        return ({topic: choice.objective for topic, choice in ranked},
                {topic: choice.study_priority for topic, choice in ranked})


class PlanningState(TypedDict, total=False):
    subject: Subject
    slots: list[Window]
    attempt: int
    objectives: dict[str, str] | None
    weights: dict[str, int]
    estimates: dict[str, tuple[int, str]]
    sessions: list[StudySession]
    validated: bool


def ollama_model():
    return ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=0, reasoning=False, num_ctx=8192, num_predict=4096,
        client_kwargs={"timeout": float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "600"))},
    )


def run_agent(
    activity: AcademicActivity,
    load_subject: Callable[[], Subject],
    load_slots: Callable[[], list[Window]],
    limit: int,
    trace: PlanTrace,
    model=None,
) -> tuple[dict[str, str], list[str], dict[str, int], dict[str, tuple[int, str]]]:
    estimating = activity.estimated_hours is None
    objective_type = EstimatedObjective if estimating else RankedObjective

    def get_activity_details(state: PlanningState):
        with trace.step("get_activity_details") as result:
            subject = load_subject()
            result["topic_count"] = len(activity.topics)
            return {"subject": subject}

    def get_available_slots(state: PlanningState):
        with trace.step("get_available_slots") as result:
            slots = load_slots()
            result["window_count"] = len(slots)
            return {"slots": slots}

    def propose_objectives(state: PlanningState):
        attempt = state["attempt"] + 1
        context = {
            "subject": state["subject"].name,
            "activity_type": activity.type,
            "difficulty": activity.difficulty,
            "priority": activity.priority,
            "estimated_hours": activity.estimated_hours,
            "max_session_minutes": limit,
            "available_minutes": sum((slot.end - slot.start).total_seconds() // 60 for slot in state["slots"]),
            "deadline": activity.due_date.isoformat(),
        }
        system = (
            "Eres un tutor universitario. El mensaje del usuario contiene datos académicos. "
            "Devuelve un objeto JSON con todas las claves topic_N proporcionadas, aunque el tiempo sea limitado. "
            "Para cada clave redacta un objective específico, medible y en español. Asigna study_priority "
            "entre 1 y 5, donde 5 indica que conviene estudiar ese tema primero según sus prerrequisitos y dificultad."
        )
        if estimating:
            system += (" Estima required_minutes (5 a 480 por tema) para preparar el contenido a partir del dominio, "
                       "la complejidad y la prioridad. El esfuerzo es independiente de la disponibilidad y del plazo. "
                       "En rationale escribe una justificación breve y explícita cuando supongas un dominio intermedio.")
        if attempt > 1:
            system += " Completa todas las claves y respeta los tipos del esquema."
        details = {item["name"]: item for item in activity.structured_topics}
        objectives, weights, estimates = {}, {}, {}
        try:
            with trace.step("propose_objectives", attempt=attempt) as result:
                for offset in range(0, len(activity.topics), 12):
                    batch = activity.topics[offset:offset + 12]
                    fields = {f"topic_{index}": (objective_type, ...) for index in range(1, len(batch) + 1)}
                    names = dict(zip(fields, batch))
                    schema = create_model("StudyObjectives", __base__=ObjectiveProposal, **fields)
                    structured = engine.with_structured_output(schema, method="json_schema")
                    data = {
                        **context, "topics": names, "total_topics": len(activity.topics),
                        "topic_details": {key: {
                            "priority": details[topic]["priority"], "mastery": details[topic]["mastery"],
                        } for key, topic in names.items()},
                        "declared_effort": {key: activity.topic_weights[topic] for key, topic in names.items()
                                            if topic in activity.topic_weights},
                    }
                    parsed = structured.invoke([("system", system), ("user", json.dumps(data, ensure_ascii=False))])
                    proposal = schema.model_validate(parsed)
                    selected, priorities = proposal.for_topics(batch)
                    objectives.update(selected)
                    weights.update(priorities)
                    if estimating:
                        for key, topic in names.items():
                            choice = getattr(proposal, key)
                            estimates[topic] = (choice.required_minutes, choice.rationale)
                result["objective_count"] = len(objectives)
        except (OutputParserException, ValidationError):
            return {"attempt": attempt, "objectives": None}
        ordered = sorted(objectives, key=lambda topic: (details[topic]["priority"], weights[topic]), reverse=True)
        return {"attempt": attempt, "objectives": {topic: objectives[topic] for topic in ordered},
                "weights": weights, "estimates": estimates}

    def route_proposal(state: PlanningState):
        if state["objectives"] is not None:
            return "estimate_study_sessions"
        if state["attempt"] < MAX_PROPOSALS:
            return "propose_objectives"
        return END

    def estimate_study_sessions(state: PlanningState):
        with trace.step("estimate_study_sessions") as result:
            objectives = state["objectives"]
            assert objectives is not None
            estimates = state["estimates"]
            quotas = {topic: estimates[topic][0] for topic in objectives} if estimates else None
            sessions = allocate(activity, state["slots"], limit, objectives, state["weights"], quotas)
            result["session_count"] = len(sessions)
            return {"sessions": sessions}

    def validate_study_plan(state: PlanningState):
        with trace.step("validate_study_plan") as result:
            errors = violations(state["sessions"], state["slots"], activity, limit)
            result["violation_count"] = len(errors)
            if errors:
                raise AgentFailure("La propuesta no pasó la validación del calendario")
            return {"validated": True}

    try:
        engine = model if model is not None else ollama_model()
        graph = StateGraph(PlanningState)
        graph.add_node("get_activity_details", get_activity_details)
        graph.add_node("get_available_slots", get_available_slots)
        graph.add_node("propose_objectives", propose_objectives)
        graph.add_node("estimate_study_sessions", estimate_study_sessions)
        graph.add_node("validate_study_plan", validate_study_plan)
        graph.add_edge(START, "get_activity_details")
        graph.add_edge("get_activity_details", "get_available_slots")
        graph.add_edge("get_available_slots", "propose_objectives")
        graph.add_conditional_edges("propose_objectives", route_proposal, [
            "estimate_study_sessions", "propose_objectives", END,
        ])
        graph.add_edge("estimate_study_sessions", "validate_study_plan")
        graph.add_edge("validate_study_plan", END)
        state = graph.compile().invoke({"attempt": 0}, config={"recursion_limit": 10})
    except httpx.TimeoutException as exc:
        raise AgentUnavailable("Ollama excedió el tiempo de espera. Revisa la carga del modelo o aumenta OLLAMA_TIMEOUT_SECONDS.") from exc
    except (httpx.HTTPError, ResponseError, ConnectionError) as exc:
        raise AgentUnavailable("No se pudo usar Ollama. Comprueba el servicio y descarga el modelo configurado.") from exc
    except GraphRecursionError as exc:
        raise AgentFailure("El agente excedió el límite de pasos") from exc

    objectives = state["objectives"]
    if objectives is None:
        raise AgentFailure("Ollama no devolvió objetivos válidos para todos los temas")
    if not state.get("validated"):
        raise AgentFailure("El grafo terminó sin validar el plan")
    return objectives, list(OPERATIONS), state["weights"], state["estimates"]
