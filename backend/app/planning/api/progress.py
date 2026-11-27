from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from uuid import UUID

from fastapi import HTTPException


@dataclass
class Run:
    events: list[dict] = field(default_factory=list)
    finished: float | None = None


class PlanProgress:
    def __init__(self):
        self.lock = Lock()
        self.runs: dict[UUID, Run] = {}

    @contextmanager
    def track(self, key: UUID | None):
        if key is None:
            yield None
            return
        with self.lock:
            cutoff = monotonic() - 900
            self.runs = {k: v for k, v in self.runs.items() if v.finished is None or v.finished > cutoff}
            if key in self.runs and self.runs[key].finished is None:
                raise HTTPException(409, "El identificador de progreso ya está en uso")
            if len(self.runs) >= 256:
                finished = [k for k, v in self.runs.items() if v.finished is not None]
                if not finished:
                    raise HTTPException(503, "Hay demasiadas generaciones en curso")
                del self.runs[finished[0]]
            run = self.runs[key] = Run()

        def observe(event):
            with self.lock:
                run.events.append(event)

        try:
            yield observe
        finally:
            with self.lock:
                run.finished = monotonic()

    def events(self, key: UUID) -> list[dict]:
        with self.lock:
            run = self.runs.get(key)
            return list(run.events) if run else []


plan_progress = PlanProgress()
