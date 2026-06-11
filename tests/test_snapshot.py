from backend import config
from backend.agent.snapshot import build_snapshot


def test_snapshot_finds_interactive_elements(form_page_html):
    snap = build_snapshot(form_page_html, "http://test/form")
    by_name = {el.name: el for el in snap.elements if el.name}

    assert "first_name" in by_name
    assert "email" in by_name
    assert "project_type" in by_name
    # hidden inputs and display:none elements are excluded
    assert "utm_source" not in by_name


def test_snapshot_labels_and_options(form_page_html):
    snap = build_snapshot(form_page_html, "http://test/form")
    by_name = {el.name: el for el in snap.elements if el.name}

    assert by_name["first_name"].label == "First name"
    assert by_name["email"].label == "Email address"  # wrapping label
    assert by_name["zip"].label == "ZIP code"  # placeholder fallback
    assert any("windows" in opt for opt in by_name["project_type"].options)


def test_snapshot_selectors_prefer_stable_attributes(form_page_html):
    snap = build_snapshot(form_page_html, "http://test/form")
    by_name = {el.name: el for el in snap.elements if el.name}

    assert by_name["email"].selector == "input[name='email']"
    assert by_name["first_name"].selector == "#first"
    assert not by_name["email"].fragile


def test_snapshot_respects_char_budget(form_page_html):
    big_html = form_page_html.replace(
        "</body>", "<p>" + "lorem ipsum " * 5000 + "</p></body>")
    snap = build_snapshot(big_html, "http://test/form")
    text = snap.to_prompt_text()
    assert len(text) <= config.SNAPSHOT_CHAR_BUDGET + 50
    assert snap.original_size > len(text)


def test_snapshot_element_map_round_trip(form_page_html):
    snap = build_snapshot(form_page_html, "http://test/form")
    for el in snap.elements:
        assert snap.element_map[el.eid] is el
        assert el.to_line().startswith(f"{el.eid}: <")
