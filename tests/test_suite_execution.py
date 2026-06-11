"""End-to-end suite execution: two real recipes run sequentially in Chrome,
one passes, one fails, aggregate counters and child runs recorded."""
import json
import time

import pytest

from backend import db
from backend.models import Recipe, Run, RunStep, SuiteRecipe, SuiteRun, TestSuite
from backend.runs.manager import run_manager


def _recipe(session, name, steps):
    r = Recipe(name=name, definition=json.dumps({
        "version": 1, "name": name,
        "botasaurus": {"headless": True, "screenshots": False},
        "steps": steps}), variables="[]")
    session.add(r)
    session.commit()
    return r.id


@pytest.mark.browser
def test_suite_runs_recipes_and_aggregates(session_factory, fixture_server):
    with db.SessionLocal() as s:
        good = _recipe(s, "good", [
            {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
            {"type": "assert", "selector": "h1", "text_equals": "Request your free quote"},
        ])
        bad = _recipe(s, "bad", [
            {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
            {"type": "assert", "selector": "#does-not-exist", "timeout": 1,
             "message": "expected missing element"},
        ])
        suite = TestSuite(name="e2e-suite")
        s.add(suite)
        s.commit()
        s.add_all([SuiteRecipe(suite_id=suite.id, recipe_id=good, position=1),
                   SuiteRecipe(suite_id=suite.id, recipe_id=bad, position=2)])
        suite_run = SuiteRun(suite_id=suite.id, status="queued", total=2)
        s.add(suite_run)
        s.commit()
        suite_id, suite_run_id = suite.id, suite_run.id

    run_manager.start_suite_run(suite_run_id)

    deadline = time.time() + 120
    while time.time() < deadline:
        with db.SessionLocal() as s:
            sr = s.get(SuiteRun, suite_run_id)
            if sr.status not in ("queued", "running"):
                break
        time.sleep(1)

    with db.SessionLocal() as s:
        sr = s.get(SuiteRun, suite_run_id)
        children = s.query(Run).filter(Run.suite_run_id == suite_run_id).order_by(Run.id).all()
        child_statuses = [c.status for c in children]
        first_child_steps = s.query(RunStep).filter(RunStep.run_id == children[0].id).count()

    assert sr.status == "failed"  # one recipe failed
    assert sr.total == 2 and sr.passed == 1 and sr.failed == 1
    assert child_statuses == ["succeeded", "failed"]
    assert first_child_steps == 2  # child runs have browsable step timelines
