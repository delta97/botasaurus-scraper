"""Compressed page-state snapshot: the only page representation the LLM sees.

Interactive elements get short ids (e1..eN) plus generated robust selectors;
the rest of the page is reduced to a small text outline. Hard character
budget keeps token usage frugal.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Comment

from .. import config
from .selectors import generate_selector

_STRIP = ["script", "style", "noscript", "svg", "template", "link", "meta", "path"]
_INTERACTIVE = "a[href], button, input, select, textarea, [role=button], [role=link], [onclick], [contenteditable]"
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


@dataclass
class ElementInfo:
    eid: str
    tag: str
    selector: str
    fallbacks: List[str] = field(default_factory=list)
    fragile: bool = False
    type: Optional[str] = None
    name: Optional[str] = None
    label: Optional[str] = None
    text: Optional[str] = None
    href: Optional[str] = None
    options: List[str] = field(default_factory=list)
    required: bool = False

    def to_line(self) -> str:
        bits = [f"{self.eid}: <{self.tag}"]
        if self.type:
            bits.append(f" type={self.type}")
        if self.name:
            bits.append(f" name={self.name}")
        if self.required:
            bits.append(" required")
        if self.label:
            bits.append(f' label="{_trunc(self.label, 60)}"')
        if self.text and self.text != self.label:
            bits.append(f' text="{_trunc(self.text, 60)}"')
        if self.href:
            bits.append(f' href="{_trunc(self.href, 80)}"')
        if self.options:
            bits.append(f" options=[{', '.join(_trunc(o, 30) for o in self.options[:10])}]")
        bits.append(">")
        return "".join(bits)


@dataclass
class PageSnapshot:
    url: str
    title: str
    elements: List[ElementInfo]
    outline: str
    original_size: int
    compressed_size: int = 0
    element_map: Dict[str, ElementInfo] = field(default_factory=dict)

    def to_prompt_text(self, budget=None) -> str:
        budget = budget or config.SNAPSHOT_CHAR_BUDGET
        lines = [f"URL: {self.url}", f"TITLE: {self.title}", "", "INTERACTIVE ELEMENTS:"]
        lines.extend(el.to_line() for el in self.elements)
        lines.append("")
        lines.append("PAGE OUTLINE:")
        lines.append(self.outline)
        text = "\n".join(lines)
        if len(text) > budget:
            text = text[:budget] + "\n...[truncated]"
        return text


def _trunc(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _is_hidden(node) -> bool:
    if node.get("hidden") is not None or node.get("aria-hidden") == "true":
        return True
    if node.name == "input" and node.get("type") == "hidden":
        return True
    style = node.get("style") or ""
    return bool(_HIDDEN_STYLE.search(style))


def _label_for(node, soup) -> Optional[str]:
    if node.get("aria-label"):
        return node["aria-label"]
    node_id = node.get("id")
    if node_id:
        label = soup.select_one(f"label[for='{node_id}']")
        if label:
            return label.get_text(" ", strip=True)
    wrapping = node.find_parent("label")
    if wrapping:
        return wrapping.get_text(" ", strip=True)
    if node.get("placeholder"):
        return node["placeholder"]
    if node.name == "input" and node.get("type") in ("submit", "button") and node.get("value"):
        return node["value"]
    return None


def _outline(soup, budget=2500) -> str:
    lines = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "legend", "th"]):
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        if node.name.startswith("h"):
            lines.append(f"{'#' * int(node.name[1])} {_trunc(text, 100)}")
        else:
            lines.append(_trunc(text, 90))
        if sum(len(l) + 1 for l in lines) > budget:
            break
    # dedupe consecutive repeats (menus often duplicate text)
    deduped = [l for i, l in enumerate(lines) if i == 0 or l != lines[i - 1]]
    return "\n".join(deduped)[:budget]


def build_snapshot(html: str, url: str, title: str = "") -> PageSnapshot:
    original_size = len(html or "")
    soup = BeautifulSoup(html or "", "lxml")

    for tag in soup(_STRIP):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    if not title and soup.title:
        title = soup.title.get_text(strip=True)

    elements: List[ElementInfo] = []
    seen_nodes = set()
    for node in soup.select(_INTERACTIVE):
        if id(node) in seen_nodes or _is_hidden(node):
            continue
        seen_nodes.add(id(node))
        if len(elements) >= config.MAX_INTERACTIVE_ELEMENTS:
            break

        sel = generate_selector(node, soup)
        info = ElementInfo(
            eid=f"e{len(elements) + 1}",
            tag=node.name,
            selector=sel.primary,
            fallbacks=sel.fallbacks,
            fragile=sel.fragile,
            type=node.get("type"),
            name=node.get("name"),
            label=_label_for(node, soup),
            required=node.get("required") is not None,
        )
        if node.name == "a":
            info.href = node.get("href")
            info.text = node.get_text(" ", strip=True)[:80] or None
        elif node.name == "button":
            info.text = node.get_text(" ", strip=True)[:80] or None
        elif node.name == "select":
            info.options = [
                f"{opt.get('value', '')}:{opt.get_text(strip=True)}"
                for opt in node.find_all("option")[:10]
            ]
        elements.append(info)

    snapshot = PageSnapshot(
        url=url,
        title=title,
        elements=elements,
        outline=_outline(soup),
        original_size=original_size,
        element_map={el.eid: el for el in elements},
    )
    snapshot.compressed_size = len(snapshot.to_prompt_text())
    return snapshot
