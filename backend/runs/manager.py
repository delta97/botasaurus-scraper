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


def _run_child_replay(child_id, recipe_id, definition, variables, self_heal,
                      heal_mode, api_key, model, cancel_event, extra_result=None):
    """Replay one recipe for a suite/dataset child Run and persist its outcome.
    Returns the outcome dict."""
    from ..recipes.replay import replay_recipe

    logger = StepLogger(child_id)

    def on_step(index, step, status, error, duration_ms, result):
        detail = getattr(result, "healed", None)
        logger.log_step(
            action=step.get("type"), status=status,
            selector=(detail or {}).get("healed_selector") or step.get("selector"),
            value=step.get("value") or step.get("label") or step.get("url"),
            error=error, duration_ms=duration_ms,
            screenshot_path=result.data if step.get("type") == "screenshot" else None,
            detail=detail)

    heal = _build_heal_context(child_id, recipe_id, definition,
                               self_heal and bool(api_key), heal_mode,
                               api_key, model, logger)
    try:
        outcome = replay_recipe(
            definition, variables, on_step=on_step, heal=heal,
            screenshot_dir=config.SCREENSHOT_DIR / str(child_id),
            should_cancel=cancel_event.is_set,
            baseline_dir=config.BASELINE_DIR / str(recipe_id))
    except Exception as exc:
        outcome = {"success": False, "cancelled": False, "extracts": {},
                   "steps_executed": 0, "heals": 0,
                   "error": f"{type(exc).__name__}: {exc}"}

    with db.SessionLocal() as session:
        child = session.get(Run, child_id)
        if outcome.get("cancelled"):
            child.status = "cancelled"
        else:
            child.status = "succeeded" if outcome["success"] else "failed"
        child.error = outcome["error"]
        result = {"extracts": outcome["extracts"],
                  "steps_executed": outcome["steps_executed"],
                  "heals": outcome.get("heals", 0)}
        if extra_result:
            result.update(extra_result)
        child.result = json.dumps(result)
        child.finished_at = utcnow()
        session.commit()
    return outcome


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
        from ..recipes.replay import replay_recipe

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

    # --- suites ----------------------------------------------------------

    def start_suite_run(self, suite_run_id):
        key = f"suite-{suite_run_id}"
        cancel_event = threading.Event()

        def work():
            try:
                self._run_suite(suite_run_id, cancel_event)
            except Exception as exc:
                from ..models import SuiteRun
                self._fail_aggregate(SuiteRun, suite_run_id, f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self._runs.pop(key, None)
                try:
                    from ..notify import notify_suite_finished
                    notify_suite_finished(suite_run_id)
                except Exception:
                    pass

        self._launch(key, work, cancel_event)

    def _run_suite(self, suite_run_id, cancel_event):
        """Run every recipe in a suite sequentially under ONE semaphore hold.
        Each recipe becomes a normal child Run (suite_run_id set), so its
        timeline is browsable. A recipe's string extracts chain into later
        recipes' variables."""
        from ..models import RecipeRun, SuiteRecipe, SuiteRun
        from .. import settings_store

        with self._semaphore:
            with db.SessionLocal() as session:
                suite_run = session.get(SuiteRun, suite_run_id)
                if suite_run is None:
                    return
                suite_run.status = "running"
                suite_run.started_at = utcnow()
                session.commit()
                items = (session.query(SuiteRecipe)
                         .filter(SuiteRecipe.suite_id == suite_run.suite_id)
                         .order_by(SuiteRecipe.position, SuiteRecipe.id).all())
                recipe_map = {r.id: r for r in session.query(Recipe).filter(
                    Recipe.id.in_([i.recipe_id for i in items])).all()}
                # snapshot the rows we need so attributes survive the session close
                plan = [(i.recipe_id, json.loads(i.variables) if i.variables else {})
                        for i in items]
                recipes = {rid: {"definition": json.loads(r.definition), "name": r.name,
                                 "self_heal": bool(r.self_heal), "heal_mode": r.heal_mode or "propose"}
                           for rid, r in recipe_map.items()}
                api_key = settings_store.get_api_key(session)
                model = settings_store.get_model(session)

            passed = failed = 0
            chain = {}
            for recipe_id, item_vars in plan:
                if cancel_event.is_set():
                    break
                recipe = recipes.get(recipe_id)
                if recipe is None:
                    failed += 1
                    continue
                definition = recipe["definition"]
                variables = dict(chain)
                variables.update(item_vars)
                first_nav = next((s for s in definition.get("steps", [])
                                  if s.get("type") == "navigate"), None)
                with db.SessionLocal() as session:
                    child = Run(kind="replay", goal=f"Suite run: {recipe['name']}",
                                start_url=(first_nav or {}).get("url", ""),
                                status="running", started_at=utcnow(),
                                botasaurus_config=json.dumps(definition.get("botasaurus", {})),
                                recipe_id=recipe_id, suite_run_id=suite_run_id)
                    session.add(child)
                    session.commit()
                    child_id = child.id
                    session.add(RecipeRun(recipe_id=recipe_id, run_id=child_id,
                                          variables_used=json.dumps(variables)))
                    session.commit()

                outcome = _run_child_replay(
                    child_id, recipe_id, definition, variables, recipe["self_heal"],
                    recipe["heal_mode"], api_key, model, cancel_event)
                chain.update({k: v for k, v in outcome["extracts"].items()
                              if isinstance(v, str)})
                passed += 1 if outcome["success"] else 0
                failed += 0 if outcome["success"] else 1

            with db.SessionLocal() as session:
                suite_run = session.get(SuiteRun, suite_run_id)
                suite_run.total = len(plan)
                suite_run.passed = passed
                suite_run.failed = failed
                if cancel_event.is_set():
                    suite_run.status = "cancelled"
                else:
                    suite_run.status = "passed" if failed == 0 else "failed"
                suite_run.finished_at = utcnow()
                session.commit()

    def cancel_suite(self, suite_run_id) -> bool:
        return self.cancel(f"suite-{suite_run_id}")

    # --- datasets --------------------------------------------------------

    def start_batch_run(self, batch_run_id):
        key = f"batch-{batch_run_id}"
        cancel_event = threading.Event()

        def work():
            try:
                self._run_batch(batch_run_id, cancel_event)
            except Exception as exc:
                from ..models import BatchRun
                self._fail_aggregate(BatchRun, batch_run_id, f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self._runs.pop(key, None)

        self._launch(key, work, cancel_event)

    def _run_batch(self, batch_run_id, cancel_event):
        """Dataset replay: one child Run per row, sequentially, under one
        semaphore hold."""
        from ..models import BatchRun
        from .. import settings_store

        with self._semaphore:
            with db.SessionLocal() as session:
                batch = session.get(BatchRun, batch_run_id)
                if batch is None:
                    return
                batch.status = "running"
                batch.started_at = utcnow()
                session.commit()
                recipe = session.get(Recipe, batch.recipe_id)
                if recipe is None:
                    batch.status = "done"
                    batch.finished_at = utcnow()
                    session.commit()
                    return
                rows = json.loads(batch.rows) if batch.rows else []
                definition = json.loads(recipe.definition)
                self_heal = bool(recipe.self_heal)
                heal_mode = recipe.heal_mode or "propose"
                recipe_id = recipe.id
                api_key = settings_store.get_api_key(session)
                model = settings_store.get_model(session)

            first_nav = next((s for s in definition.get("steps", [])
                              if s.get("type") == "navigate"), None)
            succeeded = failed = 0
            for i, row in enumerate(rows):
                if cancel_event.is_set():
                    break
                with db.SessionLocal() as session:
                    child = Run(kind="replay", goal=f"Dataset row {i + 1}/{len(rows)}",
                                start_url=(first_nav or {}).get("url", ""),
                                status="running", started_at=utcnow(),
                                botasaurus_config=json.dumps(definition.get("botasaurus", {})),
                                recipe_id=recipe_id, batch_run_id=batch_run_id)
                    session.add(child)
                    session.commit()
                    child_id = child.id

                outcome = _run_child_replay(
                    child_id, recipe_id, definition, row, self_heal, heal_mode,
                    api_key, model, cancel_event, extra_result={"row": row})
                succeeded += 1 if outcome["success"] else 0
                failed += 0 if outcome["success"] else 1

            with db.SessionLocal() as session:
                batch = session.get(BatchRun, batch_run_id)
                batch.total = len(rows)
                batch.succeeded = succeeded
                batch.failed = failed
                batch.status = "cancelled" if cancel_event.is_set() else "done"
                batch.finished_at = utcnow()
                session.commit()

    def cancel_batch(self, batch_run_id) -> bool:
        return self.cancel(f"batch-{batch_run_id}")

    # --- shared infrastructure -------------------------------------------

    def _fail_aggregate(self, model_cls, agg_id, error):
        """Mark a suite/batch parent as failed when its worker crashes."""
        with db.SessionLocal() as session:
            row = session.get(model_cls, agg_id)
            if row and row.status in ("queued", "running"):
                row.status = "failed"
                if hasattr(row, "finished_at"):
                    row.finished_at = utcnow()
                session.commit()

    def _launch(self, key, work, cancel_event):
        thread = threading.Thread(target=work, daemon=True, name=key)
        with self._lock:
            self._runs[key] = {"thread": thread, "cancel": cancel_event, "started": time.time()}
        thread.start()

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
                        if isinstance(run_id, int):  # suite/batch keys are strings
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
            if run and run.status not in ("succeeded", "failed", "cancelled", "max_steps", "stalled"):
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
