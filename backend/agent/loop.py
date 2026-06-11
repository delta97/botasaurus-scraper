"""The autonomous agent loop. Runs INSIDE a single @browser-decorated function
so one driver stays alive across every step of the run.

Frugality rules implemented here:
- markdown/text extraction is pure Python (never round-trips through the LLM)
- a fill_form decision executes all its fields as a batch with no LLM calls
  in between
- failed selectors retry recorded fallbacks before the LLM is re-consulted
- only the CURRENT compressed snapshot is sent; history is one-line summaries
"""
import json
import time
from collections import deque

from .. import config, db, settings_store
from ..llm import prompts
from ..llm.openrouter import LLMError, OpenRouterClient
from ..models import Run, utcnow
from ..runs.logging import StepLogger
from .actions import ActionExecutor
from .recorder import RecipeRecorder
from .snapshot import build_snapshot


class AgentError(Exception):
    pass


# Args that label/store a result rather than change what the action DOES, so two
# extracts that differ only by destination ("into": "a" vs "b") count as the same
# action for stall detection.
_VOLATILE_ARG_KEYS = {"into", "name", "message"}


def _action_signature(name, args):
    stable = {k: v for k, v in (args or {}).items() if k not in _VOLATILE_ARG_KEYS}
    return name + ":" + json.dumps(stable, sort_keys=True, default=str)


def _load_llm(run):
    with db.SessionLocal() as session:
        api_key = settings_store.get_api_key(session)
        model = run.model or settings_store.get_model(session)
    if not api_key:
        raise AgentError("OpenRouter API key is not configured (Settings page)")
    return OpenRouterClient(api_key=api_key, model=model)


def _update_run(run_id, **fields):
    with db.SessionLocal() as session:
        run = session.get(Run, run_id)
        for key, value in fields.items():
            setattr(run, key, value)
        session.commit()


def _add_tokens(run_id, prompt_tokens, completion_tokens):
    with db.SessionLocal() as session:
        run = session.get(Run, run_id)
        run.total_prompt_tokens = (run.total_prompt_tokens or 0) + (prompt_tokens or 0)
        run.total_completion_tokens = (run.total_completion_tokens or 0) + (completion_tokens or 0)
        session.commit()


def run_agent(run_id: int, cancel_event, llm_client=None) -> str:
    """Execute an agent run. Returns the final status string."""
    from botasaurus.browser import browser  # late import: heavy
    from ..recipes.replay import build_browser_kwargs

    with db.SessionLocal() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise AgentError(f"run {run_id} not found")
        goal, start_url = run.goal, run.start_url
        cfg = json.loads(run.botasaurus_config or "{}")

    llm = llm_client or _load_llm(run)
    _update_run(run_id, model=llm.model)
    logger = StepLogger(run_id)
    recorder = RecipeRecorder()
    screenshot_dir = config.SCREENSHOT_DIR / str(run_id)
    final = {"status": "failed", "result": None, "error": None}

    @browser(**build_browser_kwargs(cfg))
    def agent_task(driver, data):
        _agent_inner_loop(driver, run_id, goal, start_url, cfg, llm, logger,
                          recorder, cancel_event, screenshot_dir, final)

    try:
        agent_task()
    except Exception as exc:
        if final["status"] == "failed" and not final["error"]:
            final["error"] = f"{type(exc).__name__}: {exc}"

    result = final["result"] or {}
    result["recorded_steps"] = recorder.steps
    _update_run(run_id, status=final["status"], result=json.dumps(result),
                error=final["error"], finished_at=utcnow())
    return final["status"]


def _maybe_screenshot(driver, cfg, screenshot_dir, step_index):
    if not cfg.get("screenshots", True):
        return None
    try:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = screenshot_dir / f"{step_index:03d}.png"
        driver.save_screenshot(str(path))
        return str(path)
    except Exception:
        return None  # screenshots are best-effort, never fail the run


def _agent_inner_loop(driver, run_id, goal, start_url, cfg, llm, logger,
                      recorder, cancel_event, screenshot_dir, final):
    executor = ActionExecutor(driver, screenshot_dir=screenshot_dir)
    pending = deque()
    history = []
    extracts = {}
    last_error = None
    steps_used = 0
    # Stall detection: (page fingerprint, action signature) of the previous
    # decision, plus how many times it has repeated unchanged.
    last_decision = None
    repeat_count = 0

    def log_and_record(name, args, result, duration_ms):
        nonlocal last_error
        shot = _maybe_screenshot(driver, cfg, screenshot_dir, logger._index)
        try:
            page_url = driver.current_url
        except Exception:
            page_url = None
        logger.log_step(
            action=name,
            status="ok" if result.ok else "error",
            page_url=page_url,
            selector=result.selector,
            value=result.value,
            error=result.error,
            screenshot_path=shot,
            duration_ms=duration_ms,
        )
        if result.ok:
            recorder.record(name, result, args)
            if result.data is not None:
                key = args.get("into") or f"{name}_{logger._index}"
                extracts[key] = result.data
                history.append(f"{name} -> stored {len(str(result.data))} chars as '{key}'")
            else:
                history.append(f"{name} {result.selector or result.value or ''} -> ok")
            last_error = None
        else:
            history.append(f"{name} {result.selector or ''} -> FAILED: {result.error}")
            last_error = f"{name}: {result.error}"

    # Step 0: initial navigation is deterministic — no LLM needed to start.
    start = time.time()
    nav = executor.execute("navigate", {"url": start_url,
                                        "bypass_cloudflare": cfg.get("bypass_cloudflare", False)})
    log_and_record("navigate", {"url": start_url,
                                "bypass_cloudflare": cfg.get("bypass_cloudflare", False)},
                   nav, int((time.time() - start) * 1000))
    if not nav.ok:
        final["status"] = "failed"
        final["error"] = f"could not open {start_url}: {nav.error}"
        return

    while steps_used < config.MAX_AGENT_STEPS:
        if cancel_event.is_set():
            final["status"] = "cancelled"
            final["error"] = "cancelled by user"
            return

        if not pending:
            # Ask the LLM for the next action against a fresh snapshot.
            try:
                snap = build_snapshot(driver.page_html, driver.current_url)
            except Exception as exc:
                final["error"] = f"could not snapshot page: {exc}"
                return
            executor.set_snapshot(snap)
            snap_text = snap.to_prompt_text()
            messages = [
                {"role": "system", "content": prompts.SYSTEM_PROMPT},
                {"role": "user", "content": prompts.build_user_message(
                    goal, snap_text, history, last_error)},
            ]
            t0 = time.time()
            try:
                response = llm.chat(messages, tools=prompts.AGENT_TOOLS, tool_choice="required")
            except LLMError as exc:
                logger.log_llm_call(model=llm.model, purpose="decide_action",
                                    request_messages=messages, error=str(exc),
                                    latency_ms=int((time.time() - t0) * 1000))
                final["error"] = f"LLM call failed: {exc}"
                return
            logger.log_llm_call(
                model=llm.model, purpose="decide_action", request_messages=messages,
                response_content=response.raw or {
                    "tool_calls": [{"name": tc.name, "arguments": tc.arguments}
                                   for tc in response.tool_calls]},
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=int((time.time() - t0) * 1000),
            )
            _add_tokens(run_id, response.prompt_tokens, response.completion_tokens)

            if not response.tool_calls:
                last_error = "you must respond with a tool call"
                steps_used += 1
                continue

            tool = response.tool_calls[0]
            if tool.name == "finish":
                success = bool(tool.arguments.get("success"))
                final["status"] = "succeeded" if success else "failed"
                if not success:
                    final["error"] = tool.arguments.get("summary")
                if cfg.get("output_format") == "markdown" and not extracts:
                    # final page as markdown, deterministic
                    try:
                        from .markdown import html_to_markdown
                        extracts["page_markdown"] = html_to_markdown(driver.page_html)
                    except Exception:
                        pass
                final["result"] = {
                    "summary": tool.arguments.get("summary"),
                    "answer": tool.arguments.get("result"),
                    "extracts": extracts,
                }
                return

            # Stall guard: same action decided against an unchanged page N times
            # running means the model is looping (weak models re-extract instead
            # of calling finish). Abort now rather than re-sending identical
            # snapshots until the step budget runs out.
            decision = (hash(snap_text), _action_signature(tool.name, tool.arguments))
            if decision == last_decision:
                repeat_count += 1
            else:
                last_decision = decision
                repeat_count = 1
            if repeat_count >= config.STALL_REPEAT_LIMIT:
                final["status"] = "stalled"
                final["error"] = (
                    f"stopped after the model repeated '{tool.name}' "
                    f"{repeat_count}x on an unchanged page without finishing — "
                    f"it is likely stuck. Try a more capable model.")
                final["result"] = {"summary": None, "answer": None, "extracts": extracts}
                return

            if tool.name == "fill_form":
                # Batch: execute every field without re-consulting the LLM.
                for fld in tool.arguments.get("fields", []):
                    eid = fld.get("element_id")
                    el = snap.element_map.get(eid) if eid else None
                    action = "select_option" if (el and el.tag == "select") else "type"
                    pending.append((action, fld))
            else:
                pending.append((tool.name, tool.arguments))

        name, args = pending.popleft()
        t0 = time.time()
        result = executor.execute(name, args)
        log_and_record(name, args, result, int((time.time() - t0) * 1000))
        steps_used += 1
        if not result.ok:
            pending.clear()  # page state is now uncertain; replan from a fresh snapshot

    final["status"] = "max_steps"
    final["error"] = f"stopped after {config.MAX_AGENT_STEPS} steps without finishing"
    final["result"] = {"summary": None, "answer": None, "extracts": extracts}
