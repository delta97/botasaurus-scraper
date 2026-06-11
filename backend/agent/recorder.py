"""Records every successfully executed agent action as a deterministic recipe
step, so a finished run can be saved and replayed without AI."""
import re
from typing import List, Optional


class RecipeRecorder:
    RECORDABLE = {"navigate", "click", "type", "select_option", "wait_for",
                  "scroll", "extract_markdown", "extract_text", "run_js", "screenshot"}

    def __init__(self):
        self.steps: List[dict] = []

    def record(self, action: str, exec_result, args: dict):
        if action not in self.RECORDABLE or not exec_result.ok:
            return
        step = {"type": action}
        if action == "navigate":
            step["url"] = exec_result.value
            if args.get("bypass_cloudflare"):
                step["bypass_cloudflare"] = True
        else:
            if exec_result.selector:
                step["selector"] = exec_result.selector
            if exec_result.fallbacks:
                step["selector_fallbacks"] = exec_result.fallbacks[:2]
            if exec_result.fragile:
                step["fragile"] = True
        if action == "type":
            step["value"] = exec_result.value
        elif action == "select_option":
            if args.get("value") is not None:
                step["value"] = args["value"]
            elif args.get("label") is not None:
                step["label"] = args["label"]
        elif action == "scroll":
            if not exec_result.selector:
                step["to"] = "bottom" if exec_result.value == "bottom" else "down"
        elif action in ("extract_markdown", "extract_text", "run_js"):
            if args.get("into"):
                step["into"] = args["into"]
            if action == "run_js":
                step["script"] = args["script"]
        elif action == "screenshot":
            step["name"] = exec_result.value
        self.steps.append(step)


_NAME_HINT = re.compile(r"\[name='([^']+)'\]|\[placeholder='([^']+)'\]|#([A-Za-z][\w-]*)")


def _variable_name(step: dict, taken) -> str:
    base = None
    match = _NAME_HINT.search(step.get("selector") or "")
    if match:
        base = next(g for g in match.groups() if g)
    base = re.sub(r"\W+", "_", (base or "value")).strip("_").lower() or "value"
    name, i = base, 1
    while name in taken:
        i += 1
        name = f"{base}_{i}"
    return name


def variablize_steps(steps: List[dict]):
    """Turn literal typed values into {{variables}} so saved recipes can be
    replayed with different data. Returns (new_steps, variables)."""
    variables = []
    taken = set()
    new_steps = []
    for step in steps:
        step = dict(step)
        if step.get("type") == "type" and step.get("value"):
            var = _variable_name(step, taken)
            taken.add(var)
            variables.append({"name": var, "default": step["value"]})
            step["value"] = "{{" + var + "}}"
        new_steps.append(step)
    return new_steps, variables


def build_recipe_definition(name: str, steps: List[dict], botasaurus_config: dict,
                            description: Optional[str] = None, output_format: str = "json",
                            variablize: bool = True) -> dict:
    if variablize:
        steps, variables = variablize_steps(steps)
    else:
        variables = []
    # screenshots/output_format are app-level settings, not replay behavior knobs
    bota = {k: v for k, v in (botasaurus_config or {}).items() if k != "output_format"}
    from .selectors import SELECTOR_SPEC_VERSION
    return {
        "version": 1,
        "name": name,
        "description": description,
        "variables": variables,
        "botasaurus": bota,
        "output_format": output_format,
        "steps": steps,
        "selector_spec_version": SELECTOR_SPEC_VERSION,
        "source": "agent",
    }
