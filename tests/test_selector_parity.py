"""Python half of the JS<->Python selector parity check. The Node half
(extension/test/selector.test.js) runs the SAME fixtures through the
extension's selector.js and asserts the SAME cases.json — so the two selector
engines cannot drift without a test failing in one runtime or the other."""
import json
from pathlib import Path

from bs4 import BeautifulSoup

from backend.agent.selectors import SELECTOR_SPEC_VERSION, generate_selector

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "selectors"
CASES = json.loads((FIXTURE_DIR / "cases.json").read_text())


def test_spec_version_matches_fixtures():
    assert CASES["selector_spec_version"] == SELECTOR_SPEC_VERSION


def test_python_matches_golden_cases():
    for case in CASES["cases"]:
        html = (FIXTURE_DIR / case["file"]).read_text()
        soup = BeautifulSoup(html, "lxml")
        node = soup.select_one("[data-fixture-target]")
        assert node is not None, f"{case['file']} has no [data-fixture-target]"
        res = generate_selector(node, soup)
        got = {"primary": res.primary, "fallbacks": res.fallbacks, "fragile": res.fragile}
        assert got == case["expected"], f"{case['file']}: {got} != {case['expected']}"
