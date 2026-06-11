"""Regression tests for worker-thread resilience (the C1 fix): a crashing
suite/batch worker must not strand the registry or leave the parent 'running',
and a restart must clear orphaned aggregates."""
import time

from backend import db
from backend.models import BatchRun, Recipe, Run, SuiteRun, TestSuite
from backend.runs.manager import RunManager


def _wait_inactive(mgr, key, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not mgr.is_active(key):
            return True
        time.sleep(0.05)
    return False


def test_suite_worker_survives_missing_row(session_factory):
    """A SuiteRun row that vanishes before the worker starts must not strand
    the registry key (it would otherwise crash before cleanup)."""
    mgr = RunManager()
    # suite_run_id that doesn't exist -> _run_suite returns early / _fail_aggregate no-ops
    mgr.start_suite_run(99999)
    assert _wait_inactive(mgr, "suite-99999"), "registry key leaked after crash"


def test_batch_worker_marks_parent_failed_on_crash(session_factory, monkeypatch):
    """If the batch worker raises mid-flight, the BatchRun must end 'failed',
    not stay 'running' forever."""
    with db.SessionLocal() as s:
        recipe = Recipe(name="r", variables="[]",
                        definition='{"version":1,"name":"r","steps":[]}')
        s.add(recipe)
        s.commit()
        batch = BatchRun(recipe_id=recipe.id, status="queued", total=1,
                         rows='[{"x": "1"}]')
        s.add(batch)
        s.commit()
        batch_id = batch.id

    # force a crash inside the worker after it sets status=running
    import backend.runs.manager as m
    monkeypatch.setattr(m, "_run_child_replay",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    mgr = RunManager()
    mgr.start_batch_run(batch_id)
    assert _wait_inactive(mgr, f"batch-{batch_id}")

    with db.SessionLocal() as s:
        batch = s.get(BatchRun, batch_id)
    assert batch.status == "failed"  # not stuck on 'running'
    assert batch.finished_at is not None


def test_fail_orphaned_clears_aggregates(session_factory):
    """A restart (fail_orphaned_runs) must clear stuck suite/batch parents,
    not just the runs table."""
    with db.SessionLocal() as s:
        suite = TestSuite(name="s")
        recipe = Recipe(name="r", variables="[]", definition='{"version":1,"name":"r","steps":[]}')
        s.add_all([suite, recipe])
        s.commit()
        s.add_all([
            Run(kind="replay", start_url="x", status="running"),
            SuiteRun(suite_id=suite.id, status="running", total=1),
            BatchRun(recipe_id=recipe.id, status="queued", total=1),
        ])
        s.commit()

    cleared = db.fail_orphaned_runs()
    assert cleared == 3

    with db.SessionLocal() as s:
        assert s.query(SuiteRun).filter(SuiteRun.status == "failed").count() == 1
        assert s.query(BatchRun).filter(BatchRun.status == "failed").count() == 1
        assert s.query(Run).filter(Run.status == "failed").count() == 1
