"""Worker-thread registry. One daemon thread per run; a semaphore serializes
actual browser usage (one Chrome at a time), so extra runs stay 'queued'."""
import json
import threading
import time

from .. import config, db
from ..models import Run, utcnow
from .logging import StepLogger


class RunManager:
    def __init__(self, max_concurrent_browsers=1):
        self._semaphore = threading.Semaphore(max_concurrent_browsers)
        self._runs = {}
        self._lock = threading.Lock()

    def start_agent_run(self, run_id, llm_client=None):
        from ..agent.loop import run_agent

        def target(cancel_event):
            return run_agent(run_id, cancel_event, llm_client=llm_client)

        self._spawn(run_id, target)

    def start_replay_run(self, run_id, definition, variables, botasaurus_overrides=None):
        from ..recipes.replay import replay_recipe

        def target(cancel_event):
            logger = StepLogger(run_id)

            def on_step(index, step, status, error, duration_ms, result):
                logger.log_step(
                    action=step.get("type"),
                    status=status,
                    selector=step.get("selector"),
                    value=step.get("value") or step.get("label") or step.get("url"),
                    error=error,
                    duration_ms=duration_ms,
                    screenshot_path=result.data if step.get("type") == "screenshot" else None,
                )

            outcome = replay_recipe(
                definition, variables, botasaurus_overrides, on_step=on_step,
                screenshot_dir=config.SCREENSHOT_DIR / str(run_id),
            )
            with db.SessionLocal() as session:
                run = session.get(Run, run_id)
                run.status = "succeeded" if outcome["success"] else "failed"
                run.error = outcome["error"]
                run.result = json.dumps({"extracts": outcome["extracts"],
                                         "steps_executed": outcome["steps_executed"]})
                run.finished_at = utcnow()
                session.commit()
            return run_id

        self._spawn(run_id, target)

    def _spawn(self, run_id, target):
        cancel_event = threading.Event()

        def work():
            with self._semaphore:
                if cancel_event.is_set():
                    self._finish(run_id, "cancelled", "cancelled while queued")
                    return
                with db.SessionLocal() as session:
                    run = session.get(Run, run_id)
                    run.status = "running"
                    run.started_at = utcnow()
                    session.commit()
                try:
                    target(cancel_event)
                except Exception as exc:
                    self._finish(run_id, "failed", f"{type(exc).__name__}: {exc}")
                finally:
                    with self._lock:
                        self._runs.pop(run_id, None)

        thread = threading.Thread(target=work, daemon=True, name=f"run-{run_id}")
        with self._lock:
            self._runs[run_id] = {"thread": thread, "cancel": cancel_event, "started": time.time()}
        thread.start()

    def _finish(self, run_id, status, error):
        with db.SessionLocal() as session:
            run = session.get(Run, run_id)
            if run and run.status not in ("succeeded", "failed", "cancelled", "max_steps"):
                run.status = status
                run.error = error
                run.finished_at = utcnow()
                session.commit()

    def cancel(self, run_id) -> bool:
        with self._lock:
            entry = self._runs.get(run_id)
        if entry:
            entry["cancel"].set()
            return True
        return False

    def is_active(self, run_id) -> bool:
        with self._lock:
            return run_id in self._runs


run_manager = RunManager()
