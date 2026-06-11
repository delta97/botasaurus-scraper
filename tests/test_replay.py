"""End-to-end deterministic replay against a locally served form page.
Needs Chrome; skipped automatically when it isn't installed."""
import pytest


@pytest.mark.browser
def test_replay_fills_form_and_asserts_confirmation(fixture_server):
    from backend.recipes.replay import replay_recipe

    definition = {
        "version": 1,
        "name": "fixture-lead-form",
        "variables": [
            {"name": "first_name", "default": "John"},
            {"name": "email", "default": "john@example.com"},
        ],
        "botasaurus": {"headless": True, "screenshots": False},
        "steps": [
            {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
            {"type": "type", "selector": "input[name='first_name']", "value": "{{first_name}}"},
            {"type": "type", "selector": "input[name='email']", "value": "{{email}}"},
            {"type": "select_option", "selector": "select[name='project_type']", "value": "windows"},
            {"type": "click", "selector": "#lead-form button[type='submit']"},
            {"type": "assert", "selector": "#thanks", "message": "confirmation missing"},
            {"type": "extract_text", "selector": "#thanks", "into": "confirmation"},
        ],
    }

    seen = []
    outcome = replay_recipe(
        definition, {"first_name": "Jane"},
        on_step=lambda i, step, status, error, ms, result: seen.append((step["type"], status)),
    )

    assert outcome["success"], outcome["error"]
    assert outcome["steps_executed"] == 7
    assert all(status == "ok" for _, status in seen)
    assert "Thank you Jane" in outcome["extracts"]["confirmation"]


@pytest.mark.browser
def test_replay_optional_step_failure_continues(fixture_server):
    from backend.recipes.replay import replay_recipe

    definition = {
        "version": 1,
        "name": "optional-steps",
        "botasaurus": {"headless": True, "screenshots": False},
        "steps": [
            {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
            {"type": "click", "selector": "#does-not-exist", "optional": True, "wait": 1},
            {"type": "extract_text", "selector": "h1", "into": "heading"},
        ],
    }
    outcome = replay_recipe(definition)
    assert outcome["success"]
    assert "free quote" in outcome["extracts"]["heading"].lower()


def test_replay_unknown_variable_fails_before_browser_launch():
    from backend.recipes.replay import replay_recipe
    from backend.recipes.schema import RecipeError

    definition = {
        "version": 1,
        "name": "bad-vars",
        "steps": [{"type": "type", "selector": "input", "value": "{{missing}}"}],
    }
    with pytest.raises(RecipeError, match="unknown variable"):
        replay_recipe(definition)
