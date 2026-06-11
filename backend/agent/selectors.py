"""Generate replay-robust CSS selectors for DOM nodes.

Priority: stable #id > [name=] > [data-testid]/[aria-label] > [placeholder=]
> a[href*=] > nth-of-type path (flagged fragile). Every candidate is verified
unique against the parsed document before being chosen.

The ladder constants and the unstable-id regex are loaded from
extension/shared/selector-spec.json so that the JS recorder in the Chrome
extension (extension/content/selector.js) stays byte-for-byte in sync with
this module. Golden fixtures in tests/fixtures/selectors/ enforce parity.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

_SPEC_PATH = Path(__file__).resolve().parents[2] / "extension" / "shared" / "selector-spec.json"
with open(_SPEC_PATH) as _f:
    SELECTOR_SPEC = json.load(_f)

SELECTOR_SPEC_VERSION = SELECTOR_SPEC["selector_spec_version"]
_ATTRIBUTE_LADDER = SELECTOR_SPEC["attribute_ladder"]
_HREF_MIN_SEGMENT = SELECTOR_SPEC["href_min_segment_length"]
_INPUT_TYPE_SELF = set(SELECTOR_SPEC["input_type_self_selectors"])
_MAX_FALLBACKS = SELECTOR_SPEC["max_fallbacks"]

# ids that look auto-generated: long hex, uuid chunks, long digit runs,
# framework ids like ":r3:" / "ember123" / "__next..."
_flags = re.I if "i" in SELECTOR_SPEC.get("unstable_id_flags", "") else 0
_UNSTABLE_ID = re.compile(SELECTOR_SPEC["unstable_id_regex"], _flags)


@dataclass
class SelectorResult:
    primary: str
    fallbacks: List[str] = field(default_factory=list)
    fragile: bool = False


def css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def looks_stable_id(value: str) -> bool:
    return bool(value) and not _UNSTABLE_ID.search(value)


def _attr_candidate(node, attr, prefix_tag=True):
    value = node.get(attr)
    if not value or not isinstance(value, str):
        return None
    tag = node.name if prefix_tag else ""
    return f"{tag}[{attr}='{css_escape(value)}']"


def _href_candidate(node):
    href = node.get("href")
    if not href or href.startswith(("javascript:", "#")):
        return None
    # last meaningful path segment keeps the selector short and host-agnostic
    path = re.sub(r"[?#].*$", "", href).rstrip("/")
    segment = path.rsplit("/", 1)[-1]
    if len(segment) >= _HREF_MIN_SEGMENT:
        return f"a[href*='{css_escape(segment)}']"
    return f"a[href='{css_escape(href)}']"


def _nth_path(node):
    parts = []
    current = node
    while current is not None and current.name not in (None, "[document]", "html"):
        parent = current.parent
        anchor = None
        node_id = current.get("id") if hasattr(current, "get") else None
        if node_id and looks_stable_id(node_id):
            anchor = f"#{css_escape(node_id)}"
        siblings = [s for s in (parent.find_all(current.name, recursive=False) if parent else [])]
        if len(siblings) > 1:
            index = siblings.index(current) + 1
            parts.append(anchor or f"{current.name}:nth-of-type({index})")
        else:
            parts.append(anchor or current.name)
        if anchor:
            break
        if current.name == "body":
            break
        current = parent
    return " > ".join(reversed(parts))


def _is_unique(soup, selector):
    try:
        return len(soup.select(selector)) == 1
    except Exception:
        return False


def generate_selector(node, soup) -> SelectorResult:
    candidates = []

    node_id = node.get("id")
    if node_id and looks_stable_id(node_id):
        candidates.append(f"#{css_escape(node_id)}")

    for attr in _ATTRIBUTE_LADDER:
        cand = _attr_candidate(node, attr)
        if cand:
            candidates.append(cand)

    if node.name == "a":
        cand = _href_candidate(node)
        if cand:
            candidates.append(cand)

    if node.name == "input" and node.get("type") in _INPUT_TYPE_SELF:
        candidates.append(f"input[type='{node.get('type')}']")

    unique = [c for c in candidates if _is_unique(soup, c)]
    if unique:
        return SelectorResult(primary=unique[0], fallbacks=unique[1:1 + _MAX_FALLBACKS])

    # No unique attribute selector: positional path as last resort.
    path = _nth_path(node)
    fallbacks = candidates[:_MAX_FALLBACKS]  # non-unique but better than nothing on changed pages
    return SelectorResult(primary=path, fallbacks=fallbacks, fragile=True)
