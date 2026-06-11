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
                baseline_dir=(config.BASELINE_DIR / str(recipe_id)) if recipe_id else None,
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

    def start_suite_run(self, suite_run_id):
        """Run every recipe in a suite sequentially under ONE semaphore hold.
        Each recipe becomes a normal child Run row (kind=replay, suite_run_id
        set) so its timeline is browsable like any other run."""
        from ..models import RecipeRun, SuiteRecipe, SuiteRun
        from ..recipes.replay import replay_recipe
        from .. import settings_store

        key = f"suite-{suite_run_id}"
        cancel_event = threading.Event()

        def work():
            with self._semaphore:
                with db.SessionLocal() as session:
                    suite_run = session.get(SuiteRun, suite_run_id)
                    suite_run.status = "running"
                    suite_run.started_at = utcnow()
                    session.commit()
                    items = (session.query(SuiteRecipe)
                             .filter(SuiteRecipe.suite_id == suite_run.suite_id)
                             .order_by(SuiteRecipe.position, SuiteRecipe.id).all())
                    recipes = {r.id: r for r in session.query(Recipe).filter(
                        Recipe.id.in_([i.recipe_id for i in items])).all()}
                    api_key = settings_store.get_api_key(session)
                    model = settings_store.get_model(session)

                passed = failed = 0
                for item in items:
                    if cancel_event.is_set():
                        break
                    recipe = recipes.get(item.recipe_id)
                    if recipe is None:
                        failed += 1
                        continue
                    definition = json.loads(recipe.definition)
                    variables = json.loads(item.variables) if item.variables else {}
                    first_nav = next((s for s in definition.get("steps", [])
                                      if s.get("type") == "navigate"), None)
                    with db.SessionLocal() as session:
                        child = Run(kind="replay", goal=f"Suite run: {recipe.name}",
                                    start_url=(first_nav or {}).get("url", ""),
                                    status="running", started_at=utcnow(),
                                    botasaurus_config=json.dumps(definition.get("botasaurus", {})),
                                    recipe_id=recipe.id, suite_run_id=suite_run_id)
                        session.add(child)
                        session.commit()
                        child_id = child.id
                        session.add(RecipeRun(recipe_id=recipe.id, run_id=child_id,
                                              variables_used=json.dumps(variables)))
                        session.commit()

                    logger = StepLogger(child_id)

                    def on_step(index, step, status, error, duration_ms, result,
                                _logger=logger):
                        detail = getattr(result, "healed", None)
                        _logger.log_step(
                            action=step.get("type"), status=status,
                            selector=(detail or {}).get("healed_selector") or step.get("selector"),
                            value=step.get("value") or step.get("label") or step.get("url"),
                            error=error, duration_ms=duration_ms,
                            screenshot_path=result.data if step.get("type") == "screenshot" else None,
                            detail=detail)

                    heal = _build_heal_context(child_id, recipe.id, definition,
                                               bool(recipe.self_heal) and bool(api_key),
                                               recipe.heal_mode or "propose",
                                               api_key, model, logger)
                    try:
                        outcome = replay_recipe(
                            definition, variables, on_step=on_step, heal=heal,
                            screenshot_dir=config.SCREENSHOT_DIR / str(child_id),
                            should_cancel=cancel_event.is_set,
                            baseline_dir=config.BASELINE_DIR / str(recipe.id))
                    except Exception as exc:
                        outcome = {"success": False, "cancelled": False,
                                   "error": f"{type(exc).__name__}: {exc}",
                                   "extracts": {}, "steps_executed": 0, "heals": 0}

                    with db.SessionLocal() as session:
                        child = session.get(Run, child_id)
                        if outcome.get("cancelled"):
                            child.status = "cancelled"
                        else:
                            child.status = "succeeded" if outcome["success"] else "failed"
                        child.error = outcome["error"]
                        child.result = json.dumps({"extracts": outcome["extracts"],
                                                   "steps_executed": outcome["steps_executed"],
                                                   "heals": outcome.get("heals", 0)})
                        child.finished_at = utcnow()
                        session.commit()
                    if outcome["success"]:
                        passed += 1
                    else:
                        failed += 1

                with db.SessionLocal() as session:
                    suite_run = session.get(SuiteRun, suite_run_id)
                    suite_run.total = len(items)
                    suite_run.passed = passed
                    suite_run.failed = failed
                    if cancel_event.is_set():
                        suite_run.status = "cancelled"
                    else:
                        suite_run.status = "passed" if failed == 0 else "failed"
                    suite_run.finished_at = utcnow()
                    session.commit()
                with self._lock:
                    self._runs.pop(key, None)
                try:
                    from ..notify import notify_suite_finished
                    notify_suite_finished(suite_run_id)
                except Exception:
                    pass

        thread = threading.Thread(target=work, daemon=True, name=key)
        with self._lock:
            self._runs[key] = {"thread": thread, "cancel": cancel_event, "started": time.time()}
        thread.start()

    def cancel_suite(self, suite_run_id) -> bool:
        return self.cancel(f"suite-{suite_run_id}")

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
                    try:
                        from ..notify import notify_run_finished
                        if isinstance(run_id, int):  # suite keys are strings
                            notify_run_finished(run_id)
                    except Exception:
                        pass  # notifications are best-effort

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
