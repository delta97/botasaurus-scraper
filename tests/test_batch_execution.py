"""End-to-end dataset batch + recipe chaining in real Chrome."""
import json
import time

import pytest

from backend import db
from backend.models import BatchRun, Recipe, Run, SuiteRecipe, SuiteRun, TestSuite
from backend.runs.manager import run_manager


def _wait(check, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(1)
    return False


@pytest.mark.browser
def test_batch_runs_once_per_row(session_factory, fixture_server):
    with db.SessionLocal() as s:
        recipe = Recipe(name="batch-form", variables=json.dumps(
            [{"name": "first_name", "default": "X"}]),
            definition=json.dumps({"version": 1, "name": "batch-form",
                "botasaurus": {"headless": True, "screenshots": False},
                "steps": [
                    {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
                    {"type": "type", "selector": "input[name='first_name']", "value": "{{first_name}}"},
                    {"type": "type", "selector": "input[name='email']", "value": "x@y.com"},
                    {"type": "click", "selector": "#lead-form button[type='submit']"},
                    {"type": "extract_text", "selector": "#thanks", "into": "confirmation"}]}))
        s.add(recipe)
        s.commit()
        batch = BatchRun(recipe_id=recipe.id, status="queued", total=2,
                         rows=json.dumps([{"first_name": "Ada"}, {"first_name": "Grace"}]))
        s.add(batch)
        s.commit()
        batch_id = batch.id

    run_manager.start_batch_run(batch_id)
    assert _wait(lambda: db.SessionLocal().get(BatchRun, batch_id).status == "done")

    with db.SessionLocal() as s:
        batch = s.get(BatchRun, batch_id)
        children = s.query(Run).filter(Run.batch_run_id == batch_id).order_by(Run.id).all()
        confirmations = [json.loads(c.result)["extracts"].get("confirmation") for c in children]

    assert batch.total == 2 and batch.succeeded == 2 and batch.failed == 0
    assert "Thank you Ada" in confirmations[0]
    assert "Thank you Grace" in confirmations[1]


@pytest.mark.browser
def test_suite_chaining_passes_extracts(session_factory, fixture_server):
    """Recipe A extracts the heading; recipe B types it into a field —
    proving extracts flow as variables to later suite recipes."""
    with db.SessionLocal() as s:
        producer = Recipe(name="producer", variables="[]", definition=json.dumps({
            "version": 1, "name": "producer",
            "botasaurus": {"headless": True, "screenshots": False},
            "steps": [{"type": "navigate", "url": f"{fixture_server}/form_page.html"},
                      {"type": "extract_text", "selector": "h1", "into": "heading"}]}))
        consumer = Recipe(name="consumer", variables="[]", definition=json.dumps({
            "version": 1, "name": "consumer",
            "botasaurus": {"headless": True, "screenshots": False},
            "steps": [{"type": "navigate", "url": f"{fixture_server}/form_page.html"},
                      # {{heading}} is NOT declared here; it must come from the chain
                      {"type": "type", "selector": "input[name='first_name']", "value": "{{heading}}"},
                      {"type": "extract_text", "selector": "#first", "into": "_"}]}))
        s.add_all([producer, consumer])
        s.commit()
        suite = TestSuite(name="chain")
        s.add(suite)
        s.commit()
        s.add_all([SuiteRecipe(suite_id=suite.id, recipe_id=producer.id, position=1),
                   SuiteRecipe(suite_id=suite.id, recipe_id=consumer.id, position=2)])
        suite_run = SuiteRun(suite_id=suite.id, status="queued", total=2)
        s.add(suite_run)
        s.commit()
        suite_run_id, consumer_id = suite_run.id, consumer.id

    run_manager.start_suite_run(suite_run_id)
    assert _wait(lambda: db.SessionLocal().get(SuiteRun, suite_run_id).status
                 in ("passed", "failed"))

    with db.SessionLocal() as s:
        sr = s.get(SuiteRun, suite_run_id)
        consumer_run = (s.query(Run).filter(Run.suite_run_id == suite_run_id,
                                            Run.recipe_id == consumer_id).first())
    # consumer succeeded only because {{heading}} resolved from the producer's extract
    assert sr.status == "passed", consumer_run.error
    assert consumer_run.status == "succeeded"
