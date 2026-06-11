"""Maps abstract actions (from the LLM or from recipe steps) onto Botasaurus
Driver calls. Shared by the agent loop and the deterministic recipe replayer.
"""
import json as _json
import os
import re
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
    def __init__(self, driver, screenshot_dir=None, baseline_dir=None,
                 google_referer=False):
        self.driver = driver
        self.screenshot_dir = screenshot_dir
        self.baseline_dir = baseline_dir  # visual-regression baselines
        self.google_referer = google_referer  # navigate via Driver.google_get
        self.snapshot = None  # set by the agent loop after each snapshot

    def set_snapshot(self, snapshot):
        self.snapshot = snapshot

    def _context(self, args):
        """Resolve the action context from frame_path: the driver itself, or a
        nested iframe / shadow-root wrapper. Driver, IframeElement/IframeTab and
        shadow roots all expose the same click/type/select_option/wait_for_element
        methods, so handlers can act on whatever this returns. Same-origin
        iframes only — cross-origin frames aren't reachable via selectors."""
        frame_path = args.get("frame_path") or []
        ctx = self.driver
        if not frame_path:
            return ctx
        from botasaurus_driver.driver import IframeElement, IframeTab
        for segment in frame_path:
            el = ctx.select(segment, wait=DEFAULT_WAIT)
            if el is None:
                raise ValueError(f"frame_path segment matched nothing: {segment}")
            if isinstance(el, (IframeElement, IframeTab)):
                ctx = el
            else:
                # not an iframe: treat as a shadow-DOM host
                ctx = el.get_shadow_root()
        return ctx

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
        bypass = bool(args.get("bypass_cloudflare"))
        if self.google_referer:
            self.driver.google_get(url, bypass_cloudflare=bypass)
        else:
            self.driver.get(url, bypass_cloudflare=bypass)
        return ExecResult(ok=True, value=url)

    def _do_click(self, args):
        selector, fallbacks, fragile = self._resolve(args)
        ctx = self._context(args)
        wait = args.get("wait") or DEFAULT_WAIT
        used = self._with_fallbacks(selector, fallbacks, lambda s: ctx.click(s, wait=wait))
        return ExecResult(ok=True, selector=used, fallbacks=fallbacks, fragile=fragile)

    def _do_type(self, args):
        selector, fallbacks, fragile = self._resolve(args)
        ctx = self._context(args)
        value = args.get("value", "")
        wait = args.get("wait") or DEFAULT_WAIT
        used = self._with_fallbacks(selector, fallbacks, lambda s: ctx.type(s, value, wait=wait))
        return ExecResult(ok=True, selector=used, fallbacks=fallbacks, fragile=fragile, value=value)

    def _do_select_option(self, args):
        selector, fallbacks, fragile = self._resolve(args)
        ctx = self._context(args)
        value, label = args.get("value"), args.get("label")
        wait = args.get("wait") or DEFAULT_WAIT
        if value is None and label is None:
            return ExecResult(ok=False, error="select_option needs value or label", selector=selector)

        def do(sel):
            ctx.select_option(sel, value=value, label=label, wait=wait)

        used = self._with_fallbacks(selector, fallbacks, do)
        return ExecResult(ok=True, selector=used, fallbacks=fallbacks, fragile=fragile,
                          value=value if value is not None else label)

    def _do_wait_for(self, args):
        selector, fallbacks, fragile = self._resolve(args)
        ctx = self._context(args)
        timeout = args.get("timeout") or DEFAULT_WAIT
        used = self._with_fallbacks(selector, fallbacks,
                                    lambda s: ctx.wait_for_element(s, wait=timeout))
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
        """All provided checks must pass. Checks: selector presence,
        text_contains (page), text_equals / attribute(+attribute_equals) /
        count (vs selector), url_matches (regex)."""
        timeout = args.get("timeout") or DEFAULT_WAIT
        message = args.get("message") or "assertion failed"
        selector = args.get("selector")
        checked = False

        def fail(detail):
            return ExecResult(ok=False, error=f"{message} ({detail})", selector=selector)

        if selector and args.get("count") is None:
            checked = True
            try:
                self.driver.wait_for_element(selector, wait=timeout)
            except Exception:
                return fail(f"selector not found: {selector}")

        if args.get("text_equals") is not None:
            checked = True
            if not selector:
                return fail("text_equals needs a selector")
            actual = (self.driver.get_text(selector) or "").strip()
            if actual != args["text_equals"].strip():
                return fail(f"text is {actual!r}, expected {args['text_equals']!r}")

        if args.get("attribute"):
            checked = True
            if not selector:
                return fail("attribute check needs a selector")
            actual = self.driver.get_attribute(selector, args["attribute"])
            expected = args.get("attribute_equals")
            if expected is not None and (actual or "") != expected:
                return fail(f"attribute {args['attribute']}={actual!r}, expected {expected!r}")
            if expected is None and actual is None:
                return fail(f"attribute {args['attribute']} is missing")

        if args.get("count") is not None:
            checked = True
            if not selector:
                return fail("count check needs a selector")
            actual = self.driver.run_js(
                f"return document.querySelectorAll({_json.dumps(selector)}).length")
            if int(actual or 0) != int(args["count"]):
                return fail(f"found {actual} elements matching {selector}, expected {args['count']}")

        if args.get("url_matches"):
            checked = True
            url = self.driver.current_url or ""
            if not re.search(args["url_matches"], url):
                return fail(f"url {url!r} does not match /{args['url_matches']}/")

        if args.get("text_contains"):
            checked = True
            if args["text_contains"] not in (self.driver.page_text or ""):
                return fail(f"text not found: {args['text_contains']}")

        if not checked:
            return ExecResult(ok=False, error="assert needs at least one check "
                              "(selector, text_contains, text_equals, attribute, count, url_matches)")
        return ExecResult(ok=True, selector=selector,
                          value=args.get("text_equals") or args.get("text_contains"))

    def _do_assert_screenshot(self, args):
        """Visual regression: compare a screenshot against a stored baseline.
        First run (no baseline) saves the current capture as the baseline."""
        from .visual import DEFAULT_THRESHOLD, compare_images

        name = args.get("name")
        if not name:
            return ExecResult(ok=False, error="assert_screenshot needs a name")
        if not self.baseline_dir:
            return ExecResult(ok=False, error="no baseline directory configured "
                              "(assert_screenshot is only supported for saved recipes)")

        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
        os.makedirs(self.baseline_dir, exist_ok=True)
        baseline = os.path.join(str(self.baseline_dir), f"{safe}.png")
        capture_dir = str(self.screenshot_dir or self.baseline_dir)
        os.makedirs(capture_dir, exist_ok=True)
        current = os.path.join(capture_dir, f"visual_{safe}.png")

        selector = args.get("selector")
        if selector:
            self.driver.select(selector, wait=args.get("wait") or DEFAULT_WAIT).save_screenshot(current)
        else:
            self.driver.save_screenshot(current)

        if args.get("update_baseline") or not os.path.exists(baseline):
            import shutil
            shutil.copyfile(current, baseline)
            return ExecResult(ok=True, value=f"{name} (baseline saved)", selector=selector)

        threshold = args.get("threshold")
        threshold = DEFAULT_THRESHOLD if threshold is None else float(threshold)
        diff_path = os.path.join(capture_dir, f"visual_{safe}_diff.png")
        passed, ratio, detail = compare_images(baseline, current, diff_path, threshold)
        if passed:
            return ExecResult(ok=True, value=f"{name}: {detail}", selector=selector)
        message = args.get("message") or "visual regression"
        return ExecResult(ok=False, error=f"{message}: {detail}", selector=selector,
                          value=name)
