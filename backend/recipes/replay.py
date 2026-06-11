"""Deterministic recipe replay — no LLM involved. Shared by the API replay
endpoint and the CLI runner (backend.runner)."""
import json
import os
import time
from typing import Callable, Optional

from ..agent.actions import ActionExecutor
from .schema import Recipe, substitute_all, validate_definition


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
    for key in ("proxy", "user_agent", "window_size", "profile"):
        if bota_cfg.get(key):
            kwargs[key] = bota_cfg[key]

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


def replay_recipe(definition: dict, variables: Optional[dict] = None,
                  botasaurus_overrides: Optional[dict] = None,
                  on_step: Optional[Callable] = None,
                  screenshot_dir=None) -> dict:
    """Run a recipe start to finish. Returns
    {"success": bool, "error": str|None, "extracts": {...}, "steps_executed": int}.

    on_step(index, step_dict, status, error, duration_ms, data) is called after
    every step — the API wires it to DB logging, the CLI to stdout.
    """
    from botasaurus.browser import browser  # imported late: heavy

    recipe: Recipe = validate_definition(definition)
    steps = substitute_all(recipe, variables)  # raises on unknown {{var}} before launch

    bota_cfg = recipe.botasaurus.model_dump()
    bota_cfg.update(botasaurus_overrides or {})
    bypass_cf = bool(bota_cfg.get("bypass_cloudflare"))

    outcome = {"success": True, "error": None, "extracts": {}, "steps_executed": 0}

    @browser(**build_browser_kwargs(bota_cfg))
    def replay_task(driver, data):
        executor = ActionExecutor(driver, screenshot_dir=screenshot_dir)
        for index, step in enumerate(steps):
            args = _step_args(step)
            if step.type == "navigate" and bypass_cf:
                args["bypass_cloudflare"] = True
            start = time.time()
            result = executor.execute(step.type, args)
            duration_ms = int((time.time() - start) * 1000)
            status = "ok" if result.ok else ("skipped" if step.optional else "error")
            if on_step:
                on_step(index, json.loads(step.model_dump_json(exclude_none=True)),
                        status, result.error, duration_ms, result)
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
