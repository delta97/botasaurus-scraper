"""Datasets (CSV batch), schedules (cron), recipe chaining, stealth config."""
import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend import db, scheduler
from backend.models import BatchRun, Recipe, Run


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend.main import app
    from backend.runs.manager import run_manager
    # These are endpoint tests: don't actually launch batch worker threads
    # (they'd outlive the test, try to drive Chrome, and hit a torn-down DB).
    monkeypatch.setattr(run_manager, "start_batch_run", lambda *a, **k: None)
    with TestClient(app) as c:
        db.init_db(tmp_path / "test.db")
        yield c


def _recipe(steps=None, **cols):
    with db.SessionLocal() as s:
        r = Recipe(name=cols.pop("name", "r"), variables="[]",
                   definition=json.dumps({"version": 1, "name": "r",
                       "steps": steps or [{"type": "navigate", "url": "https://x.com"}]}),
                   **cols)
        s.add(r)
        s.commit()
        return r.id


# --- datasets -------------------------------------------------------------

def test_csv_upload_creates_batch_with_rows(client):
    rid = _recipe()
    csv = "first_name,email\nAlice,a@x.com\nBob,b@x.com\n"
    res = client.post(f"/api/recipes/{rid}/batch/csv",
                      files={"file": ("data.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert res.status_code == 200
    assert res.json()["rows"] == 2
    batch_id = res.json()["batch_run_id"]

    with db.SessionLocal() as s:
        batch = s.get(BatchRun, batch_id)
        rows = json.loads(batch.rows)
    assert rows == [{"first_name": "Alice", "email": "a@x.com"},
                    {"first_name": "Bob", "email": "b@x.com"}]


def test_empty_csv_rejected(client):
    rid = _recipe()
    res = client.post(f"/api/recipes/{rid}/batch/csv",
                      files={"file": ("data.csv", io.BytesIO(b"col1,col2\n"), "text/csv")})
    assert res.status_code == 400


def test_batch_from_json_rows(client):
    rid = _recipe()
    res = client.post(f"/api/recipes/{rid}/batch", json={"rows": [{"zip": "10001"}]})
    assert res.status_code == 200 and res.json()["rows"] == 1


# --- schedules ------------------------------------------------------------

def test_schedule_crud_and_cron_validation(client):
    rid = _recipe()
    bad = client.post("/api/schedules", json={"recipe_id": rid, "cron": "not a cron"})
    assert bad.status_code == 400

    ok = client.post("/api/schedules", json={"recipe_id": rid, "cron": "0 9 * * 1",
                                             "variables": {"zip": "90210"}})
    assert ok.status_code == 200
    sid = ok.json()["id"]
    assert ok.json()["enabled"] is True

    listed = client.get("/api/schedules").json()["schedules"]
    assert any(s["id"] == sid and s["recipe_name"] == "r" for s in listed)

    upd = client.put(f"/api/schedules/{sid}", json={"enabled": False})
    assert upd.json()["enabled"] is False

    assert client.delete(f"/api/schedules/{sid}").status_code == 200
    assert all(s["id"] != sid for s in client.get("/api/schedules").json()["schedules"])


def test_scheduler_fires_recipe(client, monkeypatch):
    """A schedule fire creates a queued Run and calls start_replay_run."""
    rid = _recipe()
    started = []
    from backend.runs.manager import run_manager
    monkeypatch.setattr(run_manager, "start_replay_run",
                        lambda *a, **k: started.append((a, k)))

    from backend.models import Schedule
    with db.SessionLocal() as s:
        sch = Schedule(recipe_id=rid, cron="* * * * *", enabled=1,
                       variables=json.dumps({"zip": "12345"}))
        s.add(sch)
        s.commit()
        sid = sch.id

    scheduler._fire(sid)  # invoke the job body directly

    assert len(started) == 1
    with db.SessionLocal() as s:
        runs = s.query(Run).filter(Run.recipe_id == rid).all()
        sch = s.get(Schedule, sid)
    assert len(runs) == 1 and runs[0].status == "queued"
    assert sch.last_run_id == runs[0].id


def test_disabled_schedule_does_not_fire(client):
    rid = _recipe()
    from backend.models import Schedule
    with db.SessionLocal() as s:
        sch = Schedule(recipe_id=rid, cron="* * * * *", enabled=0)
        s.add(sch)
        s.commit()
        sid = sch.id
    scheduler._fire(sid)
    with db.SessionLocal() as s:
        assert s.query(Run).filter(Run.recipe_id == rid).count() == 0


# --- stealth config -------------------------------------------------------

def test_stealth_config_maps_to_browser_kwargs():
    from backend.recipes.replay import build_browser_kwargs
    kwargs = build_browser_kwargs({"headless": True, "window_size": "1920,1080"})
    assert kwargs["window_size"] == (1920, 1080)  # parsed to tuple
    # human_mode / google_referer are applied on the driver, not decorator kwargs
    assert "human_mode" not in kwargs and "google_referer" not in kwargs


def test_google_referer_uses_google_get():
    from backend.agent.actions import ActionExecutor

    class FakeDriver:
        def __init__(self): self.calls = []
        def get(self, url, **k): self.calls.append(("get", url))
        def google_get(self, url, **k): self.calls.append(("google_get", url))

    d = FakeDriver()
    ActionExecutor(d, google_referer=True).execute("navigate", {"url": "https://x.com"})
    assert d.calls == [("google_get", "https://x.com")]

    d2 = FakeDriver()
    ActionExecutor(d2, google_referer=False).execute("navigate", {"url": "https://x.com"})
    assert d2.calls == [("get", "https://x.com")]
