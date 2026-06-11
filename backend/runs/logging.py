"""DB-backed step/LLM-call logging for runs. Each write uses a short-lived
session so worker threads never hold long transactions against SQLite."""
import json

from .. import db
from ..models import LlmCall, RunStep


class StepLogger:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self._index = 0

    def log_step(self, action, status, page_url=None, selector=None, value=None,
                 error=None, screenshot_path=None, duration_ms=None, detail=None) -> int:
        index = self._index
        self._index += 1
        with db.SessionLocal() as session:
            step = RunStep(
                run_id=self.run_id,
                step_index=index,
                action=action,
                status=status,
                page_url=_trunc(page_url, 1000),
                selector=_trunc(selector, 1000),
                value=_trunc(value, 2000),
                error=_trunc(error, 4000),
                screenshot_path=screenshot_path,
                duration_ms=duration_ms,
                detail=json.dumps(detail) if detail else None,
            )
            session.add(step)
            session.commit()
            return step.id

    def log_llm_call(self, model, purpose, request_messages, response_content=None,
                     prompt_tokens=None, completion_tokens=None, latency_ms=None,
                     error=None, step_id=None):
        with db.SessionLocal() as session:
            session.add(LlmCall(
                run_id=self.run_id,
                step_id=step_id,
                model=model,
                purpose=purpose,
                request_messages=json.dumps(request_messages),
                response_content=json.dumps(response_content) if response_content is not None else None,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                error=_trunc(error, 4000),
            ))
            session.commit()


def _trunc(value, limit):
    if value is None:
        return None
    value = str(value)
    return value if len(value) <= limit else value[:limit] + "...[truncated]"
