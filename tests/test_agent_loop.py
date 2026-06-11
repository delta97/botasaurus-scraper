"""Full agent-loop smoke test with a scripted MockLLM — no OpenRouter key,
but a real browser against the local fixture server."""
import json
import threading

import pytest

from backend import db
from backend.models import LlmCall, Run, RunStep


@pytest.mark.browser
def test_agent_fills_lead_form_with_mock_llm(session_factory, fixture_server):
    from backend.agent.loop import run_agent
    from backend.llm.mock import MockLLMClient

    with db.SessionLocal() as session:
        run = Run(
            kind="agent",
            goal="Fill out the lead form with John Doe / john@example.com and submit it",
            start_url=f"{fixture_server}/form_page.html",
            status="running",
            botasaurus_config=json.dumps({"headless": True, "screenshots": False}),
        )
        session.add(run)
        session.commit()
        run_id = run.id

    # The mock decides like the real LLM would: one batched fill_form using
    # element ids from the snapshot, then click submit, then finish.
    mock = MockLLMClient([
        ("fill_form", {"fields": [
            {"selector": "input[name='first_name']", "value": "John"},
            {"selector": "input[name='last_name']", "value": "Doe"},
            {"selector": "input[name='email']", "value": "john@example.com"},
        ]}),
        ("click", {"selector": "#lead-form button[type='submit']"}),
        ("extract_text", {"selector": "#thanks", "into": "confirmation"}),
        ("finish", {"success": True, "summary": "Form submitted"}),
    ])

    status = run_agent(run_id, threading.Event(), llm_client=mock)
    assert status == "succeeded"

    with db.SessionLocal() as session:
        run = session.get(Run, run_id)
        result = json.loads(run.result)
        steps = (session.query(RunStep).filter(RunStep.run_id == run_id)
                 .order_by(RunStep.step_index).all())
        llm_calls = session.query(LlmCall).filter(LlmCall.run_id == run_id).all()

    assert "Thank you John" in result["extracts"]["confirmation"]
    assert result["summary"] == "Form submitted"

    actions = [s.action for s in steps]
    assert actions[0] == "navigate"
    assert actions.count("type") == 3  # fill_form expanded into a batch
    assert "click" in actions
    assert all(s.status == "ok" for s in steps)

    # frugality: 4 decisions from the LLM, but 6 browser actions executed
    assert len(llm_calls) == 4
    # recorded recipe is replayable
    recorded = result["recorded_steps"]
    assert recorded[0]["type"] == "navigate"
    assert any(s["type"] == "type" and s.get("value") == "john@example.com" for s in recorded)


@pytest.mark.browser
def test_agent_handles_failed_action_and_finishes(session_factory, fixture_server):
    from backend.agent.loop import run_agent
    from backend.llm.mock import MockLLMClient

    with db.SessionLocal() as session:
        run = Run(
            kind="agent", goal="click a missing button",
            start_url=f"{fixture_server}/form_page.html",
            status="running",
            botasaurus_config=json.dumps({"headless": True, "screenshots": False}),
        )
        session.add(run)
        session.commit()
        run_id = run.id

    mock = MockLLMClient([
        ("click", {"selector": "#missing-button", "wait": 1}),
        ("finish", {"success": False, "summary": "button does not exist"}),
    ])

    status = run_agent(run_id, threading.Event(), llm_client=mock)
    assert status == "failed"

    # the failure was fed back to the LLM in the next user message
    last_messages = mock.calls[-1]["messages"]
    assert "FAILED" in last_messages[-1]["content"] or "failed" in last_messages[-1]["content"].lower()
