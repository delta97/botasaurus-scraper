"""Heal review endpoints: list, accept (patches the recipe), reject."""
import json

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.models import Recipe, RecipeHeal


@pytest.fixture()
def client(tmp_path):
    from backend.main import app
    with TestClient(app) as c:
        db.init_db(tmp_path / "test.db")
        yield c


def _seed_recipe_with_heal(status="proposed"):
    definition = {
        "version": 1, "name": "r",
        "steps": [
            {"type": "navigate", "url": "https://x.com"},
            {"type": "click", "selector": "button.old", "selector_fallbacks": []},
        ],
    }
    with db.SessionLocal() as session:
        recipe = Recipe(name="r", definition=json.dumps(definition), variables="[]")
        session.add(recipe)
        session.commit()
        heal = RecipeHeal(recipe_id=recipe.id, run_id=None, step_index=1,
                          original_selector="button.old", healed_selector="button.new",
                          healed_fallbacks=json.dumps(["form button"]),
                          element_label="Submit", status=status)
        session.add(heal)
        session.commit()
        return recipe.id, heal.id


def test_list_heals(client):
    recipe_id, heal_id = _seed_recipe_with_heal()
    r = client.get(f"/api/recipes/{recipe_id}/heals")
    assert r.status_code == 200
    heals = r.json()["heals"]
    assert len(heals) == 1
    assert heals[0]["healed_selector"] == "button.new"
    assert heals[0]["status"] == "proposed"


def test_accept_patches_recipe_step(client):
    recipe_id, heal_id = _seed_recipe_with_heal()
    r = client.post(f"/api/recipes/{recipe_id}/heals/{heal_id}/accept")
    assert r.status_code == 200 and r.json()["status"] == "accepted"

    definition = client.get(f"/api/recipes/{recipe_id}").json()["definition"]
    assert definition["steps"][1]["selector"] == "button.new"
    assert definition["steps"][1]["selector_fallbacks"] == ["form button"]
    assert definition["version"] == 2  # bumped


def test_reject_leaves_recipe_unchanged(client):
    recipe_id, heal_id = _seed_recipe_with_heal()
    before = client.get(f"/api/recipes/{recipe_id}").json()["definition"]
    r = client.post(f"/api/recipes/{recipe_id}/heals/{heal_id}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    after = client.get(f"/api/recipes/{recipe_id}").json()["definition"]
    assert after["steps"][1]["selector"] == before["steps"][1]["selector"] == "button.old"


def test_invalid_decision_rejected(client):
    recipe_id, heal_id = _seed_recipe_with_heal()
    r = client.post(f"/api/recipes/{recipe_id}/heals/{heal_id}/maybe")
    assert r.status_code == 400


def test_self_heal_flag_settable(client):
    recipe_id, _ = _seed_recipe_with_heal()
    r = client.put(f"/api/recipes/{recipe_id}", json={"self_heal": True, "heal_mode": "auto"})
    assert r.status_code == 200
    got = client.get(f"/api/recipes/{recipe_id}").json()
    assert got["self_heal"] is True and got["heal_mode"] == "auto"
