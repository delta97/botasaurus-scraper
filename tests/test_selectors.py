from bs4 import BeautifulSoup

from backend.agent.selectors import generate_selector, looks_stable_id


def _node(html, selector):
    soup = BeautifulSoup(html, "lxml")
    return soup.select_one(selector), soup


def test_stable_id_preferred():
    node, soup = _node("<form><input id='email-input' name='email'></form>", "input")
    result = generate_selector(node, soup)
    assert result.primary == "#email-input"
    assert "input[name='email']" in result.fallbacks
    assert not result.fragile


def test_unstable_ids_rejected():
    assert not looks_stable_id("a3f8b2c91d4e")  # hex blob
    assert not looks_stable_id("input-48271")  # long digit run
    assert not looks_stable_id(":r3:")  # react auto id
    assert not looks_stable_id("ember123")
    assert looks_stable_id("email-input")
    assert looks_stable_id("submitBtn")

    node, soup = _node("<input id='x9f3aa8b201' name='email'>", "input")
    result = generate_selector(node, soup)
    assert result.primary == "input[name='email']"


def test_nth_path_fallback_is_fragile():
    html = "<div><p><button>One</button><button>Two</button></p></div>"
    node, soup = _node(html, "p button:nth-of-type(2)")
    result = generate_selector(node, soup)
    assert result.fragile
    assert "nth-of-type(2)" in result.primary
    assert len(soup.select(result.primary)) == 1


def test_link_selector_uses_href_segment():
    html = "<a href='/services/window-replacement?id=1'>Windows</a><a href='/about'>About</a>"
    node, soup = _node(html, "a")
    result = generate_selector(node, soup)
    assert result.primary == "a[href*='window-replacement']"


def test_quotes_escaped_in_attribute_values():
    html = """<input name="it's['weird']" type="text">"""
    node, soup = _node(html, "input")
    result = generate_selector(node, soup)
    assert len(soup.select(result.primary)) == 1
