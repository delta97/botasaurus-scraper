"""Suites CRUD, JUnit export, run diffing, and webhook notification."""
import json

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.models import Recipe, Run, RunStep, SuiteRecipe, SuiteRun, TestSuite, utcnow


@pytest.fixture()
def client(tmp_path):
    from backend.main import app
    with TestClient(app) as c:
        db.init_db(tmp_path / "test.db")
        yield c


def _seed_recipe(name="r1"):
    with db.SessionLocal() as s:
        r = Recipe(name=name, definition=json.dumps({
            "version": 1, "name": name,
            "steps": [{"type": "navigate", "url": "https://x.com"}]}), variables="[]")
        s.add(r)
        s.commit()
        return r.id


def test_suite_crud_flow(client):
    r1, r2 = _seed_recipe("alpha"), _seed_recipe("beta")
    suite_id = client.post("/api/suites", json={"name": "smoke"}).json()["suite_id"]

    client.post(f"/api/suites/{suite_id}/recipes", json={"recipe_id": r1})
    client.post(f"/api/suites/{suite_id}/recipes", json={"recipe_id": r2,
                                                         "variables": {"zip": "10001"}})
    suite = client.get(f"/api/suites/{suite_id}").json()
    assert [r["name"] for r in suite["recipes"]] == ["alpha", "beta"]
    assert suite["recipes"][1]["variables"] == {"zip": "10001"}

    sr_id = suite["recipes"][0]["suite_recipe_id"]
    client.delete(f"/api/suites/{suite_id}/recipes/{sr_id}")
    assert len(client.get(f"/api/suites/{suite_id}").json()["recipes"]) == 1

    listed = client.get("/api/suites").json()["suites"]
    assert listed[0]["recipe_count"] == 1


def test_run_empty_suite_rejected(client):
    suite_id = client.post("/api/suites", json={"name": "empty"}).json()["suite_id"]
    r = client.post(f"/api/suites/{suite_id}/run")
    assert r.status_code == 400


def _seed_suite_run(client):
    """Seed a finished suite run with one passed and one failed child."""
    recipe_id = _seed_recipe("seeded")
    suite_id = client.post("/api/suites", json={"name": "ci-suite"}).json()["suite_id"]
    with db.SessionLocal() as s:
        suite_run = SuiteRun(suite_id=suite_id, status="failed", total=2, passed=1, failed=1,
                             started_at="2026-06-11T00:00:00+00:00",
                             finished_at="2026-06-11T00:01:00+00:00")
        s.add(suite_run)
        s.commit()
        s.add(Run(kind="replay", goal="Suite run: good", start_url="x", status="succeeded",
                  recipe_id=recipe_id, suite_run_id=suite_run.id,
                  started_at="2026-06-11T00:00:00+00:00",
                  finished_at="2026-06-11T00:00:20+00:00"))
        s.add(Run(kind="replay", goal="Suite run: bad", start_url="x", status="failed",
                  error='step 2 failed: selector "broke" & gone',
                  recipe_id=recipe_id, suite_run_id=suite_run.id,
                  started_at="2026-06-11T00:00:20+00:00",
                  finished_at="2026-06-11T00:01:00+00:00"))
        s.commit()
        return suite_id, suite_run.id


def test_suite_run_detail_and_junit(client):
    suite_id, suite_run_id = _seed_suite_run(client)

    detail = client.get(f"/api/suites/{suite_id}/runs/{suite_run_id}").json()
    assert detail["status"] == "failed"
    assert [c["status"] for c in detail["children"]] == ["succeeded", "failed"]

    xml = client.get(f"/api/suites/{suite_id}/runs/{suite_run_id}/junit.xml")
    assert xml.status_code == 200
    body = xml.text
    assert 'tests="2"' in body and 'failures="1"' in body
    assert '<testcase classname="ci-suite" name="good"' in body
    assert "<failure" in body and "&amp; gone" in body  # XML-escaped

    import xml.etree.ElementTree as ET
    root = ET.fromstring(body)  # well-formed
    assert root.tag == "testsuite"


def test_run_diff_endpoint(client):
    with db.SessionLocal() as s:
        a = Run(kind="replay", start_url="x", status="succeeded",
                result=json.dumps({"extracts": {"title": "Hello", "same": 1}}))
        b = Run(kind="replay", start_url="x", status="failed",
                result=json.dumps({"extracts": {"title": "Changed", "same": 1, "new": 2}}))
        s.add_all([a, b])
        s.commit()
        s.add_all([
            RunStep(run_id=a.id, step_index=0, action="navigate", status="ok", duration_ms=100),
            RunStep(run_id=a.id, step_index=1, action="click", selector=".x", status="ok", duration_ms=50),
            RunStep(run_id=b.id, step_index=0, action="navigate", status="ok", duration_ms=110),
            RunStep(run_id=b.id, step_index=1, action="click", selector=".x", status="error",
                    error="gone", duration_ms=4000),
            RunStep(run_id=b.id, step_index=2, action="assert", status="error", duration_ms=10),
        ])
        s.commit()
        a_id, b_id = a.id, b.id

    diff = client.get(f"/api/runs/{a_id}/diff/{b_id}").json()
    by_index = {row["index"]: row for row in diff["steps"]}
    assert not by_index[0]["changed"]
    assert by_index[1]["changed"]            # ok -> error
    assert by_index[2]["a"] is None and by_index[2]["changed"]  # extra step in b
    assert diff["extracts_diff"]["changed"] == ["title"]
    assert diff["extracts_diff"]["only_b"] == ["new"]


def test_webhook_fires_on_failure(session_factory):
    """notify_run_finished posts to the configured URL only for failures."""
    import http.server
    import threading

    from backend import settings_store
    from backend.notify import notify_run_finished

    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/hook"

    try:
        with db.SessionLocal() as s:
            settings_store.set_setting(s, settings_store.KEY_WEBHOOK_URL, url)
            ok_run = Run(kind="replay", goal="fine", start_url="x", status="succeeded")
            bad_run = Run(kind="replay", goal="broken flow", start_url="https://x.com",
                          status="failed", error="step 1 failed")
            s.add_all([ok_run, bad_run])
            s.commit()
            ok_id, bad_id = ok_run.id, bad_run.id

        assert notify_run_finished(ok_id) is False   # successes are silent
        assert notify_run_finished(bad_id) is True
        assert len(received) == 1
        payload = received[0]
        assert payload["status"] == "failed"
        assert "broken flow" in payload["text"]      # Slack field
        assert "broken flow" in payload["content"]   # Discord field
        assert payload["run_id"] == bad_id
    finally:
        server.shutdown()
