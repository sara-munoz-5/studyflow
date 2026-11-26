import json
import logging
from contextlib import contextmanager
from time import monotonic
from uuid import uuid4

logger = logging.getLogger("uvicorn.error")


class PlanTrace:
    def __init__(self, activity_id: int, observer=None):
        self.run_id = uuid4().hex
        self.activity_id = activity_id
        self.observer = observer

    @contextmanager
    def step(self, name: str, **metrics):
        start = monotonic()
        result = {}
        error = None
        if self.observer:
            self.observer({"step": name, "outcome": "running"})
        try:
            yield result
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            event = {
                "event": "studyflow.plan.step",
                "run_id": self.run_id,
                "activity_id": self.activity_id,
                "step": name,
                "duration_ms": round((monotonic() - start) * 1000),
                "outcome": "error" if error else "ok",
                **metrics,
                **result,
            }
            if error:
                event["error_type"] = error
            if self.observer:
                self.observer({"step": name, "outcome": event["outcome"]})
            logger.log(logging.WARNING if error else logging.INFO, "%s", json.dumps(event))
