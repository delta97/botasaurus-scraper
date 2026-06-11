"""Worker-thread registry. One daemon thread per run; a semaphore serializes
actual browser usage (one Chrome at a time), so extra runs stay 'queued'."""
import json
import threading
import time

from .. import config, db
from ..models import Recipe, RecipeHeal, Run, utcnow
from .logging import StepLogger


def _build_heal_context(run_id, recipe_id, definition, self_heal, heal_mode,
                        api_key, model, logger):
    """Build a HealContext if self-healing is enabled and a key is available.
    Returns None otherwise (replay then stays fully AI-free)."""
    if not self_heal or not api_key:
        return None
    from ..llm.openrouter import OpenRouterClient
    from ..recipes.replay import HealContext

    llm = OpenRouterClient(api_key=api_key, model=model or config.DEFAULT_MODEL)

    def log_llm(purpose, messages, response, latency_ms, error):
        return logger.log_llm_call(model=llm.model, purpose=purpose,
                                   request_messages=messages, response_content=response,
                                   latency_ms=latency_ms, error=error)

    def on_heal(index, step_dict, healed):
        if recipe_id is None:
            return  # file-based CLI replay: nothing in the DB to patch
        with db.SessionLocal() as session:
            applied = heal_mode == "auto"
            session.add(RecipeHeal(
                recipe_id=recipe_id, run_id=run_id, step_index=index,
                original_selector=healed["original_selector"],
                healed_selector=healed["healed_selector"],
                healed_fallbacks=json.dumps(healed["healed_fallbacks"]),
                element_label=healed.get("element_label"),
                status="applied" if applied else "proposed",
                llm_call_id=healed.get("llm_call_id"),
            ))
            if applied:
                _patch_recipe_step(session, recipe_id, index,
                                   healed["healed_selector"], healed["healed_fallbacks"])
            session.commit()

    return HealContext(llm=llm, mode=heal_mode, on_heal=on_heal, log_llm=log_llm)


def _patch_recipe_step(session, recipe_id, index, selector, fallbacks):
    recipe = session.get(Recipe, recipe_id)
    if not recipe:
        return
    definition = json.loads(recipe.definition)
    steps = definition.get("steps", [])
    if 0 <= index < len(steps):
        steps[index]["selector"] = selector
        steps[index]["selector_fallbacks"] = fallbacks
        steps[index].pop("fragile", None)
        definition["version"] = definition.get("version", 1) + 1
        recipe.definition = json.dumps(definition)
        recipe.updated_at = utcnow()


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

    def start_replay_run(self, run_id, definition, variables, botasaurus_overrides=None,
                         recipe_id=None, self_heal=False, heal_mode="propose",
                         api_key=None, model=None):
        from ..recipes.replay import HealContext, replay_recipe

        def target(cancel_event):
            logger = StepLogger(run_id)

            def on_step(index, step, status, error, duration_ms, result):
                detail = getattr(result, "healed", None)
                logger.log_step(
                    action=step.get("type"),
                    status=status,
                    selector=(detail or {}).get("healed_selector") or step.get("selector"),
                    value=step.get("value") or step.get("label") or step.get("url"),
                    error=error,
                    duration_ms=duration_ms,
                    screenshot_path=result.data if step.get("type") == "screenshot" else None,
                    detail=detail,
                )

            heal = _build_heal_context(run_id, recipe_id, definition, self_heal,
                                       heal_mode, api_key, model, logger)
            outcome = replay_recipe(
                definition, variables, botasaurus_overrides, on_step=on_step,
                screenshot_dir=config.SCREENSHOT_DIR / str(run_id), heal=heal,
                should_cancel=cancel_event.is_set,
            )
            with db.SessionLocal() as session:
                run = session.get(Run, run_id)
                if outcome.get("cancelled"):
                    run.status = "cancelled"
                else:
                    run.status = "succeeded" if outcome["success"] else "failed"
                run.error = outcome["error"]
                run.result = json.dumps({"extracts": outcome["extracts"],
                                         "steps_executed": outcome["steps_executed"],
                                         "heals": outcome.get("heals", 0)})
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
