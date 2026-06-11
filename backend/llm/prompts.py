"""System prompt and tool (action) schemas for the autonomous agent."""

SYSTEM_PROMPT = """\
You are a careful web automation agent controlling a real Chrome browser.
You are given a GOAL, the CURRENT PAGE state (URL, interactive elements with \
ids like e1/e2/..., and a text outline), and a history of actions already taken.

Rules:
- Respond with EXACTLY ONE tool call per turn. Never reply with plain text.
- Refer to elements by their element_id (e.g. "e7") from the CURRENT page \
snapshot. Only use a raw CSS selector if the element you need is not listed.
- Prefer fill_form to set several fields of the same form in one turn — it is \
cheaper and faster than typing field by field.
- To read page content, use extract_markdown / extract_text — these run \
locally without you seeing the raw HTML, and the result is stored for the user.
- If the previous action failed, the error is shown; try a different element \
or approach rather than repeating the same action.
- When the goal is achieved (or is impossible), call finish with an honest \
summary. Set success=false if you could not achieve the goal.
- Stay on task. Only interact with pages and elements needed for the goal.
"""

# OpenAI/OpenRouter tool-calling schemas. One function per browser action.
_EL = {
    "element_id": {"type": "string", "description": "Element id from the snapshot, e.g. 'e7'. Preferred."},
    "selector": {"type": "string", "description": "Raw CSS selector. Only if no element_id fits."},
}

AGENT_TOOLS = [
    {"type": "function", "function": {
        "name": "navigate",
        "description": "Navigate the browser to a URL.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
        }, "required": ["url"]},
    }},
    {"type": "function", "function": {
        "name": "click",
        "description": "Click an element (link, button, checkbox...).",
        "parameters": {"type": "object", "properties": {**_EL}},
    }},
    {"type": "function", "function": {
        "name": "type",
        "description": "Type text into an input or textarea (replaces existing value).",
        "parameters": {"type": "object", "properties": {
            **_EL, "value": {"type": "string"},
        }, "required": ["value"]},
    }},
    {"type": "function", "function": {
        "name": "fill_form",
        "description": "Fill multiple form fields in one batch (text inputs and selects). Use this instead of many separate type calls.",
        "parameters": {"type": "object", "properties": {
            "fields": {"type": "array", "items": {"type": "object", "properties": {
                **_EL,
                "value": {"type": "string", "description": "Text to type, or option value/label for selects."},
            }, "required": ["value"]}},
        }, "required": ["fields"]},
    }},
    {"type": "function", "function": {
        "name": "select_option",
        "description": "Choose an option in a <select> dropdown by option value or visible label.",
        "parameters": {"type": "object", "properties": {
            **_EL,
            "value": {"type": "string", "description": "Option value attribute."},
            "label": {"type": "string", "description": "Visible option text (alternative to value)."},
        }},
    }},
    {"type": "function", "function": {
        "name": "scroll",
        "description": "Scroll the page (to load more content or reveal elements).",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string", "enum": ["bottom", "down"], "description": "'bottom' scrolls fully, 'down' one viewport."},
            "selector": {"type": "string", "description": "Scroll this element into view instead."},
        }},
    }},
    {"type": "function", "function": {
        "name": "wait_for",
        "description": "Wait until an element appears (e.g. after navigation or async load).",
        "parameters": {"type": "object", "properties": {
            **_EL, "timeout": {"type": "integer", "description": "Seconds, default 8."},
        }},
    }},
    {"type": "function", "function": {
        "name": "extract_markdown",
        "description": "Convert the page (or one element) to markdown and store it in the run result. Runs locally — cheap.",
        "parameters": {"type": "object", "properties": {
            "selector": {"type": "string", "description": "Optional CSS selector; default is the whole page."},
            "into": {"type": "string", "description": "Result key to store under, e.g. 'article'."},
        }},
    }},
    {"type": "function", "function": {
        "name": "extract_text",
        "description": "Extract visible text of the page (or one element) and store it in the run result.",
        "parameters": {"type": "object", "properties": {
            "selector": {"type": "string"},
            "into": {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "run_js",
        "description": "Run JavaScript in the page as a last resort when no other action works.",
        "parameters": {"type": "object", "properties": {
            "script": {"type": "string"},
            "into": {"type": "string", "description": "Store the return value in the result under this key."},
        }, "required": ["script"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "End the task. Call when the goal is achieved or cannot be achieved.",
        "parameters": {"type": "object", "properties": {
            "success": {"type": "boolean"},
            "summary": {"type": "string", "description": "What was done / why it failed."},
            "result": {"type": "string", "description": "Optional final answer or extracted data summary."},
        }, "required": ["success", "summary"]},
    }},
]


def build_user_message(goal, snapshot_text, history_lines, last_error=None):
    parts = [f"GOAL: {goal}", ""]
    if history_lines:
        parts.append("ACTIONS TAKEN SO FAR:")
        parts.extend(f"  {line}" for line in history_lines[-15:])
        parts.append("")
    if last_error:
        parts.append(f"LAST ACTION FAILED: {last_error}")
        parts.append("")
    parts.append("CURRENT PAGE:")
    parts.append(snapshot_text)
    parts.append("")
    parts.append("Choose exactly one tool call for the next action.")
    return "\n".join(parts)


# --- Self-healing: relocate a recorded element whose selector no longer matches.
HEAL_SYSTEM_PROMPT = """\
A recorded browser-automation step can no longer find its target element (the \
page changed). Given the step's intent and the CURRENT page, pick the element_id \
that best matches the original element, or report that no element matches.
Respond with exactly one `relocate` tool call. Prefer an element of the same \
kind (a button stays a button, an email field stays an email field) and the same \
visible label/text as the original."""

HEAL_TOOLS = [
    {"type": "function", "function": {
        "name": "relocate",
        "description": "Identify the element on the current page matching the broken step.",
        "parameters": {"type": "object", "properties": {
            "found": {"type": "boolean", "description": "True if a matching element exists on this page."},
            "element_id": {"type": "string", "description": "The matching element id (e.g. 'e7'). Required when found=true."},
            "reason": {"type": "string", "description": "Brief justification."},
        }, "required": ["found"]},
    }},
]


def build_heal_message(step, snapshot_text):
    """step: a dict with type/selector/value/label and recorded hints."""
    desc = [f"BROKEN STEP: {step.get('type')}"]
    if step.get("selector"):
        desc.append(f"  original selector (now failing): {step['selector']}")
    for key, label in (("element_label", "label"), ("element_text", "text"),
                       ("tag", "tag"), ("input_type", "input type"), ("value", "value being entered")):
        if step.get(key):
            desc.append(f"  {label}: {step[key]}")
    return "\n".join([
        "\n".join(desc), "",
        "CURRENT PAGE:", snapshot_text, "",
        "Call relocate with the matching element_id, or found=false if none matches.",
    ])
