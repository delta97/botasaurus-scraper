"""Deterministic recipe replay. Normally NO LLM is involved; the optional
self-healing path (HealContext) calls the LLM only when a step's selector
breaks. Shared by the API replay endpoint and the CLI runner (backend.runner).
"""
import json
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..agent.actions import ActionExecutor
from .schema import Recipe, substitute_all, validate_definition

# Steps whose failure is worth trying to heal (they resolve a selector).
HEALABLE_TYPES = {"click", "type", "select_option", "wait_for", "assert"}
MAX_HEALS_PER_RUN = 5


@dataclass
class HealContext:
    """Carries the LLM client + behaviour for self-healing a replay. None of
    its callbacks are required (the CLI may run without DB logging)."""
    llm: object                      # OpenRouterClient or MockLLMClient
    mode: str = "propose"            # 'propose' | 'auto'
    on_heal: Optional[Callable] = None      # (index, step_dict, healed_dict) -> None
    log_llm: Optional[Callable] = None      # (purpose, messages, response, latency, error) -> llm_call_id
    attempts_remaining: int = MAX_HEALS_PER_RUN

    def can_attempt(self):
        return self.attempts_remaining > 0

    def consume(self):
        self.attempts_remaining -= 1


def build_browser_kwargs(bota_cfg: dict) -> dict:
    """Translate our config block into @browser decorator kwargs."""
    kwargs = {
        "headless": bool(bota_cfg.get("headless", True)),
        "wait_for_complete_page_load": bool(bota_cfg.get("wait_for_complete_page_load", True)),
        "block_images": bool(bota_cfg.get("block_images", False)),
        "block_images_and_css": bool(bota_cfg.get("block_images_and_css", False)),
        "max_retry": 0,  # retries are handled at run level, not per browser launch
        "close_on_crash": True,  # never pause for manual debugging on a server
        "output": None,
        "create_error_logs": False,
        "raise_exception": True,
        "enable_xvfb_virtual_display": bool(bota_cfg.get("enable_xvfb_virtual_display", False)),
    }
    for key in ("proxy", "user_agent", "profile"):
        if bota_cfg.get(key):
            kwargs[key] = bota_cfg[key]

    # window_size is stored as "W,H" in our config but botasaurus wants a (w, h) pair
    window_size = bota_cfg.get("window_size")
    if window_size:
        if isinstance(window_size, str):
            try:
                w, h = (int(x) for x in window_size.replace("x", ",").split(","))
                kwargs["window_size"] = (w, h)
            except (ValueError, TypeError):
                pass  # malformed; fall back to the browser default
        else:
            kwargs["window_size"] = window_size

    extra_args = list(bota_cfg.get("add_arguments") or [])
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        # Chrome refuses to start as root without --no-sandbox; small /dev/shm
        # in containers crashes tabs without --disable-dev-shm-usage.
        for arg in ("--no-sandbox", "--disable-dev-shm-usage"):
            if arg not in extra_args:
                extra_args.append(arg)
    if extra_args:
        kwargs["add_arguments"] = extra_args
    return kwargs


def _step_args(step) -> dict:
    args = step.model_dump(exclude_none=True)
    args.pop("type", None)
    args.pop("optional", None)
    args.pop("fragile", None)
    return args


def _attempt_heal(executor, driver, step, step_dict, args, heal: HealContext):
    """Relocate a broken element with the LLM and retry the step once. Returns
    the retry ExecResult (with .healed set) on success, else None. Bounded to a
    single retry per failed step, capped by heal.attempts_remaining."""
    from ..agent.snapshot import build_snapshot
    from ..llm import prompts

    heal.consume()
    try:
        snap = build_snapshot(driver.page_html, driver.current_url)
    except Exception:
        return None
    executor.set_snapshot(snap)

    messages = [
        {"role": "system", "content": prompts.HEAL_SYSTEM_PROMPT},
        {"role": "user", "content": prompts.build_heal_message(step_dict, snap.to_prompt_text())},
    ]
    t0 = time.time()
    try:
        resp = heal.llm.chat(messages, tools=prompts.HEAL_TOOLS, tool_choice="required")
    except Exception as exc:
        if heal.log_llm:
            heal.log_llm("heal", messages, None, int((time.time() - t0) * 1000), str(exc))
        executor.set_snapshot(None)
        return None
    llm_call_id = None
    if heal.log_llm:
        llm_call_id = heal.log_llm("heal", messages, resp.raw or {}, int((time.time() - t0) * 1000), None)

    relocated = None
    if resp.tool_calls:
        a = resp.tool_calls[0].arguments
        if a.get("found") and a.get("element_id"):
            relocated = snap.element_map.get(a["element_id"])
    executor.set_snapshot(None)
    if relocated is None:
        return None

    retry_args = {**args, "selector": relocated.selector,
                  "selector_fallbacks": list(relocated.fallbacks)}
    retry_args.pop("element_id", None)
    result = executor.execute(step.type, retry_args)
    if not result.ok:
        return None
    result.healed = {
        "step_index": None,  # filled by caller
        "original_selector": step.selector,
        "healed_selector": relocated.selector,
        "healed_fallbacks": list(relocated.fallbacks),
        "element_label": relocated.label,
        "llm_call_id": llm_call_id,
    }
    return result


def replay_recipe(definition: dict, variables: Optional[dict] = None,
                  botasaurus_overrides: Optional[dict] = None,
                  on_step: Optional[Callable] = None,
                  screenshot_dir=None, heal: Optional[HealContext] = None,
                  should_cancel: Optional[Callable] = None,
                  baseline_dir=None) -> dict:
    """Run a recipe start to finish. Returns
    {"success": bool, "error": str|None, "extracts": {...}, "steps_executed": int,
     "heals": int, "cancelled": bool}.

    on_step(index, step_dict, status, error, duration_ms, result) is called after
    every step — the API wires it to DB logging, the CLI to stdout. `heal`, when
    provided, relocates a broken selector with the LLM (one retry per step).
    `should_cancel()` is checked before each step so a running replay can be
    stopped from the UI.
    """
    from botasaurus.browser import browser  # imported late: heavy

    recipe: Recipe = validate_definition(definition)
    steps = substitute_all(recipe, variables)  # raises on unknown {{var}} before launch

    bota_cfg = recipe.botasaurus.model_dump()
    bota_cfg.update(botasaurus_overrides or {})
    bypass_cf = bool(bota_cfg.get("bypass_cloudflare"))

    outcome = {"success": True, "error": None, "extracts": {}, "steps_executed": 0,
               "heals": 0, "cancelled": False}

    human_mode = bool(bota_cfg.get("human_mode"))
    google_referer = bool(bota_cfg.get("google_referer"))

    @browser(**build_browser_kwargs(bota_cfg))
    def replay_task(driver, data):
        if human_mode:
            driver.enable_human_mode()
        executor = ActionExecutor(driver, screenshot_dir=screenshot_dir,
                                  baseline_dir=baseline_dir, google_referer=google_referer)
        for index, step in enumerate(steps):
            if should_cancel and should_cancel():
                outcome["success"] = False
                outcome["cancelled"] = True
                outcome["error"] = "cancelled by user"
                return
            args = _step_args(step)
            if step.type == "navigate" and bypass_cf:
                args["bypass_cloudflare"] = True
            step_dict = json.loads(step.model_dump_json(exclude_none=True))
            start = time.time()
            result = executor.execute(step.type, args)

            # Self-heal: only on a selector-driven step that actually failed.
            if (not result.ok and heal and heal.can_attempt()
                    and step.type in HEALABLE_TYPES and step.selector):
                healed = _attempt_heal(executor, driver, step, step_dict, args, heal)
                if healed is not None:
                    healed.healed["step_index"] = index
                    result = healed
                    outcome["heals"] += 1
                    if heal.on_heal:
                        heal.on_heal(index, step_dict, result.healed)

            duration_ms = int((time.time() - start) * 1000)
            if result.healed:
                status = "healed"
            elif result.ok:
                status = "ok"
            elif step.optional:
                status = "skipped"
            else:
                status = "error"
            if on_step:
                on_step(index, step_dict, status, result.error, duration_ms, result)
            outcome["steps_executed"] += 1
            if result.ok and result.data is not None:
                key = step.into or f"step_{index}_{step.type}"
                outcome["extracts"][key] = result.data
            if not result.ok and not step.optional:
                outcome["success"] = False
                outcome["error"] = f"step {index} ({step.type}) failed: {result.error}"
                return

    replay_task()
    return outcome
