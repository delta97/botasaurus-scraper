"""Rich assert checks and same-origin iframe (frame_path) replay."""
import pytest


def _run(fixture_server, steps, variables=None):
    from backend.recipes.replay import replay_recipe
    return replay_recipe({
        "version": 1, "name": "assert-test",
        "botasaurus": {"headless": True, "screenshots": False},
        "steps": steps,
    }, variables)


@pytest.mark.browser
def test_rich_assertions_pass(fixture_server):
    outcome = _run(fixture_server, [
        {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
        {"type": "assert", "selector": "h1", "text_equals": "Request your free quote"},
        {"type": "assert", "selector": "#lead-form", "attribute": "id", "attribute_equals": "lead-form"},
        {"type": "assert", "url_matches": r"form_page\.html$"},
        {"type": "assert", "selector": "#lead-form input", "count": 5, "wait": 1},
        {"type": "assert", "text_contains": "our team will contact you"},
    ])
    assert outcome["success"], outcome["error"]


@pytest.mark.browser
def test_rich_assertions_fail_with_detail(fixture_server):
    outcome = _run(fixture_server, [
        {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
        {"type": "assert", "selector": "h1", "text_equals": "Wrong heading",
         "message": "heading regressed"},
    ])
    assert not outcome["success"]
    assert "heading regressed" in outcome["error"]
    assert "Request your free quote" in outcome["error"]  # actual value reported


@pytest.mark.browser
def test_assert_count_mismatch_fails(fixture_server):
    outcome = _run(fixture_server, [
        {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
        {"type": "assert", "selector": "#lead-form select", "count": 5},
    ])
    assert not outcome["success"]
    assert "expected 5" in outcome["error"]


@pytest.mark.browser
def test_frame_path_replays_inside_iframe(fixture_server):
    outcome = _run(fixture_server, [
        {"type": "navigate", "url": f"{fixture_server}/iframe_page.html"},
        {"type": "type", "selector": "input[name='first_name']", "value": "Framed",
         "frame_path": ["#form-frame"]},
        {"type": "type", "selector": "input[name='email']", "value": "f@x.com",
         "frame_path": ["#form-frame"]},
        {"type": "click", "selector": "#lead-form button[type='submit']",
         "frame_path": ["#form-frame"]},
        # the confirmation div appears inside the iframe document
        {"type": "wait_for", "selector": "#thanks", "frame_path": ["#form-frame"], "timeout": 8},
    ])
    assert outcome["success"], outcome["error"]
