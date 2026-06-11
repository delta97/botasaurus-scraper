"""Maps abstract actions (from the LLM or from recipe steps) onto Botasaurus
Driver calls. Shared by the agent loop and the deterministic recipe replayer.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from .markdown import html_to_markdown, html_to_text

DEFAULT_WAIT = 8


@dataclass
class ExecResult:
    ok: bool
    error: Optional[str] = None
    data: Any = None
    # resolved values, for logging/recording
    selector: Optional[str] = None
    fallbacks: list = field(default_factory=list)
    fragile: bool = False
    value: Optional[str] = None
    # set when a self-heal relocated the element for this step
    healed: Optional[dict] = None


class ActionExecutor:
    def __init__(self, driver, screenshot_dir=None):
        self.driver = driver
        self.screenshot_dir = screenshot_dir
        self.snapshot = None  # set by the agent loop after each snapshot

    def set_snapshot(self, snapshot):
        self.snapshot = snapshot

    def _resolve(self, args):
        """element_id (snapshot) or raw selector -> (selector, fallbacks, fragile)."""
        eid = args.get("element_id")
        if eid and self.snapshot and eid in self.snapshot.element_map:
            el = self.snapshot.element_map[eid]
            return el.selector, list(el.fallbacks), el.fragile
        if eid and not args.get("selector"):
            raise ValueError(f"unknown element_id '{eid}' (not in current page snapshot)")
        selector = args.get("selector")
        if not selector:
            raise ValueError("action needs an element_id or selector")
        return selector, list(args.get("selector_fallbacks") or []), False

    def _with_fallbacks(self, selector, fallbacks, fn):
        last_exc = None
        for sel in [selector] + fallbacks:
            try:
                fn(sel)
                return sel
            except Exception as exc:  # botasaurus raises driver-specific errors
                last_exc = exc
        raise last_exc

    def execute(self, name, args) -> ExecResult:
        handler = getattr(self, f"_do_{name}", None)
        if handler is None:
            return ExecResult(ok=False, error=f"unknown action: {name}")
        try:
            return handler(args)
        except Exception as exc:
            result = ExecResult(ok=False, error=f"{type(exc).__name__}: {exc}")
            try:
                result.selector = self._resolve(args)[0]
            except Exception:
                result.selector = args.get("selector")
            result.value = args.get("value")
            return result

    # --- handlers ---------------------------------------------------------

    def _do_navigate(self, args):
        url = args["url"]
        self.driver.get(url, bypass_cloudflare=bool(args.get("bypass_cloudflare")))
        return ExecResult(ok=True, value=url)

    def _do_click(self, args):
        selector, fallbacks, fragile = self._resolve(args)
        wait = args.get("wait") or DEFAULT_WAIT
        used = self._with_fallbacks(selector, fallbacks, lambda s: self.driver.click(s, wait=wait))
        return ExecResult(ok=True, selector=used, fallbacks=fallbacks, fragile=fragile)

    def _do_type(self, args):
        selector, fallbacks, fragile = self._resolve(args)
        value = args.get("value", "")
        wait = args.get("wait") or DEFAULT_WAIT
        used = self._with_fallbacks(selector, fallbacks, lambda s: self.driver.type(s, value, wait=wait))
        return ExecResult(ok=True, selector=used, fallbacks=fallbacks, fragile=fragile, value=value)

    def _do_select_option(self, args):
        selector, fallbacks, fragile = self._resolve(args)
        value, label = args.get("value"), args.get("label")
        wait = args.get("wait") or DEFAULT_WAIT
        if value is None and label is None:
            return ExecResult(ok=False, error="select_option needs value or label", selector=selector)

        def do(sel):
            self.driver.select_option(sel, value=value, label=label, wait=wait)

        used = self._with_fallbacks(selector, fallbacks, do)
        return ExecResult(ok=True, selector=used, fallbacks=fallbacks, fragile=fragile,
                          value=value if value is not None else label)

    def _do_wait_for(self, args):
        selector, fallbacks, fragile = self._resolve(args)
        timeout = args.get("timeout") or DEFAULT_WAIT
        used = self._with_fallbacks(selector, fallbacks,
                                    lambda s: self.driver.wait_for_element(s, wait=timeout))
        return ExecResult(ok=True, selector=used, fallbacks=fallbacks, fragile=fragile)

    def _do_scroll(self, args):
        selector = args.get("selector")
        if selector:
            self.driver.scroll(selector)
            return ExecResult(ok=True, selector=selector)
        if args.get("to") == "bottom":
            self.driver.scroll_to_bottom()
        else:
            self.driver.scroll()
        return ExecResult(ok=True, value=args.get("to") or "down")

    def _do_extract_markdown(self, args):
        data = html_to_markdown(self.driver.page_html, args.get("selector"))
        return ExecResult(ok=True, data=data, selector=args.get("selector"))

    def _do_extract_text(self, args):
        data = html_to_text(self.driver.page_html, args.get("selector"))
        return ExecResult(ok=True, data=data, selector=args.get("selector"))

    def _do_run_js(self, args):
        data = self.driver.run_js(args["script"])
        return ExecResult(ok=True, data=data, value=args["script"][:500])

    def _do_screenshot(self, args):
        name = args.get("name") or "screenshot"
        if self.screenshot_dir:
            os.makedirs(self.screenshot_dir, exist_ok=True)
            path = os.path.join(str(self.screenshot_dir), f"{name}.png")
        else:
            path = f"./{name}.png"
        self.driver.save_screenshot(path)
        return ExecResult(ok=True, data=path, value=name)

    def _do_assert(self, args):
        timeout = args.get("timeout") or DEFAULT_WAIT
        message = args.get("message") or "assertion failed"
        if args.get("selector"):
            try:
                self.driver.wait_for_element(args["selector"], wait=timeout)
                return ExecResult(ok=True, selector=args["selector"])
            except Exception:
                return ExecResult(ok=False, error=f"{message} (selector not found: {args['selector']})",
                                  selector=args["selector"])
        if args.get("text_contains"):
            if args["text_contains"] in (self.driver.page_text or ""):
                return ExecResult(ok=True, value=args["text_contains"])
            return ExecResult(ok=False, error=f"{message} (text not found: {args['text_contains']})",
                              value=args["text_contains"])
        return ExecResult(ok=False, error="assert needs selector or text_contains")
