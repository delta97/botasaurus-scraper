"""Tests for the extension-facing API: create-from-definition, pairing-token
auth, and the ping endpoint."""
import pytest
from fastapi.testclient import TestClient

from backend import db, settings_store


@pytest.fixture()
def client(tmp_path):
    from backend.main import app
    with TestClient(app) as c:
        # the app lifespan re-inits db to the default path; re-point at a tmp DB
        db.init_db(tmp_path / "test.db")
        yield c


def _token():
    with db.SessionLocal() as session:
        return settings_store.get_pairing_token(session)


VALID_DEF = {
    "version": 1,
    "name": "recorded",
    "selector_spec_version": 1,
    "source": "extension",
    "steps": [
        {"type": "navigate", "url": "https://example.com"},
        {"type": "type", "selector": "input[name='email']", "value": "{{email}}"},
    ],
    "variables": [{"name": "email", "default": ""}],
}


def test_ping_reports_versions(client):
    r = client.get("/api/extension/ping")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["api_version"] >= 1 and body["selector_spec_version"] >= 1


def test_create_recipe_requires_token(client):
    _token()  # ensure the server is paired (token exists)
    r = client.post("/api/recipes", json={"name": "x", "definition": VALID_DEF})
    assert r.status_code == 401


def test_create_recipe_rejects_wrong_token(client):
    _token()
    r = client.post("/api/recipes", json={"name": "x", "definition": VALID_DEF},
                    headers={"X-Studio-Token": "nope"})
    assert r.status_code == 401


def test_create_recipe_before_pairing_returns_503(client):
    # no token created yet -> server reports it isn't paired
    r = client.post("/api/recipes", json={"name": "x", "definition": VALID_DEF},
                    headers={"X-Studio-Token": "anything"})
    assert r.status_code == 503


def test_create_recipe_with_valid_token(client):
    token = _token()
    r = client.post("/api/recipes", json={"name": "from-ext", "definition": VALID_DEF},
                    headers={"X-Studio-Token": token})
    assert r.status_code == 200, r.text
    recipe_id = r.json()["recipe_id"]
    assert r.json()["warning"] is None

    got = client.get(f"/api/recipes/{recipe_id}").json()
    assert got["name"] == "from-ext"
    assert got["definition"]["source"] == "extension"
    assert got["variables"][0]["name"] == "email"


def test_create_recipe_warns_on_spec_mismatch(client):
    token = _token()
    mismatched = {**VALID_DEF, "selector_spec_version": 999}
    r = client.post("/api/recipes", json={"name": "old", "definition": mismatched},
                    headers={"X-Studio-Token": token})
    assert r.status_code == 200
    assert "selector spec" in r.json()["warning"]


def test_create_recipe_rejects_invalid_definition(client):
    token = _token()
    bad = {"name": "bad", "steps": [{"type": "explode"}]}
    r = client.post("/api/recipes", json={"name": "bad", "definition": bad},
                    headers={"X-Studio-Token": token})
    assert r.status_code == 422
