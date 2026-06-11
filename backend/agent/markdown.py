"""Deterministic HTML -> markdown/text conversion. Never uses the LLM."""
import re

from bs4 import BeautifulSoup
from markdownify import markdownify

_STRIP_TAGS = ["script", "style", "noscript", "svg", "template", "iframe"]


def _subtree(html: str, selector=None) -> str:
    if not selector:
        return html
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one(selector)
    if node is None:
        raise ValueError(f"selector matched nothing: {selector}")
    return str(node)


def html_to_markdown(html: str, selector=None) -> str:
    html = _subtree(html, selector)
    md = markdownify(html, heading_style="ATX", strip=_STRIP_TAGS)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def html_to_text(html: str, selector=None) -> str:
    soup = BeautifulSoup(_subtree(html, selector), "lxml")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)
