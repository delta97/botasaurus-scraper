"""Self-healing replay tests. Uses a scripted MockLLM (no OpenRouter key) and a
real browser against the local fixture server."""
import json
import threading

import pytest

from backend import db
from backend.llm.openrouter import LLMResponse, ToolCall
from backend.recipes.replay import HealContext, MAX_HEALS_PER_RUN, replay_recipe


def _broken_recipe(fixture_server):
    # The first_name selector is deliberately wrong; healing must relocate it.
    return {
        "version": 1, "name": "broken", "botasaurus": {"headless": True, "screenshots": False},
        "steps": [
            {"type": "navigate", "url": f"{fixture_server}/form_page.html"},
            {"type": "type", "selector": "input[name='does_not_exist']", "value": "Heal",
             "element_label": "First name", "tag": "input", "wait": 1},
            {"type": "extract_text", "selector": "input[name='first_name']", "into": "_"},
        ],
    }


class _HealMock:
    """Returns a relocate() call pointing at whichever snapshot element has the
    given name= in its selector."""
    def __init__(self, target_name):
        self.model = "mock/heal"
        self.target_name = target_name
        self.calls = 0

    def chat(self, messages, tools=None, tool_choice=None, **kw):
        self.calls += 1
        # find the element id in the snapshot text whose selector targets target_name
        snapshot = messages[-1]["content"]
        eid = None
        for line in snapshot.splitlines():
            if f"name={self.target_name}" in line and line.strip().startswith("e"):
                eid = line.split(":")[0].strip()
                break
        return LLMResponse(tool_calls=[ToolCall("relocate",
                          {"found": bool(eid), "element_id": eid, "reason": "matched name"})])


@pytest.mark.browser
def test_heal_relocates_broken_selector(fixture_server):
    heals = []
    llm = _HealMock("first_name")
    heal = HealContext(llm=llm, mode="propose",
                       on_heal=lambda i, step, healed: heals.append(healed))

    seen = []
    outcome = replay_recipe(_broken_recipe(fixture_server), heal=heal,
                            on_step=lambda i, s, status, e, ms, r: seen.append((s["type"], status)))

    assert outcome["success"], outcome["error"]
    assert outcome["heals"] == 1
    assert ("type", "healed") in seen
    assert llm.calls == 1
    # relocated to the snapshot's stable-id selector for the first_name input
    assert heals[0]["healed_selector"] == "#first"
    assert heals[0]["original_selector"] == "input[name='does_not_exist']"


@pytest.mark.browser
def test_heal_disabled_without_context_fails(fixture_server):
    outcome = replay_recipe(_broken_recipe(fixture_server))   # no heal
    assert not outcome["success"]
    assert "does_not_exist" in outcome["error"]


@pytest.mark.browser
def test_heal_gives_up_when_llm_finds_nothing(fixture_server):
    llm = _HealMock("never_matches_anything")   # returns found=false
    heal = HealContext(llm=llm, mode="propose")
    outcome = replay_recipe(_broken_recipe(fixture_server), heal=heal)
    assert not outcome["success"]
    assert llm.calls == 1   # one attempt, no retry loop


def test_heal_context_attempt_cap():
    heal = HealContext(llm=None)
    assert heal.attempts_remaining == MAX_HEALS_PER_RUN
    for _ in range(MAX_HEALS_PER_RUN):
        assert heal.can_attempt()
        heal.consume()
    assert not heal.can_attempt()
