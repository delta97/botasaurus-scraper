"""Visual regression: pixel-diff unit tests + assert_screenshot E2E."""
import pytest
from PIL import Image, ImageDraw

from backend.agent.visual import compare_images


def _img(path, color=(40, 80, 200), size=(200, 100), patch=None):
    img = Image.new("RGB", size, color)
    if patch:
        ImageDraw.Draw(img).rectangle(patch, fill=(255, 255, 0))
    img.save(path)
    return path


def test_identical_images_pass(tmp_path):
    a = _img(tmp_path / "a.png")
    b = _img(tmp_path / "b.png")
    passed, ratio, _ = compare_images(a, b)
    assert passed and ratio == 0.0


def test_small_change_within_threshold_passes(tmp_path):
    a = _img(tmp_path / "a.png")
    b = _img(tmp_path / "b.png", patch=(0, 0, 4, 4))  # 25px of 20000 = 0.125%
    passed, ratio, _ = compare_images(a, b, threshold=0.01)
    assert passed and 0 < ratio < 0.01


def test_large_change_fails_and_writes_diff(tmp_path):
    a = _img(tmp_path / "a.png")
    b = _img(tmp_path / "b.png", patch=(0, 0, 100, 100))
    diff = tmp_path / "diff.png"
    passed, ratio, message = compare_images(a, b, str(diff), threshold=0.01)
    assert not passed and ratio > 0.2
    assert diff.exists()
    assert "differ" in message


def test_size_mismatch_fails(tmp_path):
    a = _img(tmp_path / "a.png", size=(200, 100))
    b = _img(tmp_path / "b.png", size=(100, 100))
    passed, _, message = compare_images(a, b)
    assert not passed and "size mismatch" in message


@pytest.mark.browser
def test_assert_screenshot_baseline_then_pass_then_fail(tmp_path, fixture_server):
    from backend.recipes.replay import replay_recipe

    def recipe(extra_steps=()):
        return {
            "version": 1, "name": "visual-test",
            "botasaurus": {"headless": True, "screenshots": False,
                           "window_size": "1280,800"},
            "steps": [{"type": "navigate", "url": f"{fixture_server}/form_page.html"},
                      *extra_steps,
                      {"type": "assert_screenshot", "name": "form", "threshold": 0.01}],
        }

    baseline_dir = tmp_path / "baselines"

    # 1st run: creates the baseline and passes
    out1 = replay_recipe(recipe(), baseline_dir=baseline_dir, screenshot_dir=tmp_path)
    assert out1["success"], out1["error"]
    assert (baseline_dir / "form.png").exists()

    # 2nd run: same page, must match
    out2 = replay_recipe(recipe(), baseline_dir=baseline_dir, screenshot_dir=tmp_path)
    assert out2["success"], out2["error"]

    # 3rd run: page visually mutated -> must fail with a diff image
    mutate = {"type": "run_js",
              "script": "document.querySelector('h1').textContent = 'TOTALLY DIFFERENT'; "
                        "document.body.style.background = 'red';"}
    out3 = replay_recipe(recipe([mutate]), baseline_dir=baseline_dir, screenshot_dir=tmp_path)
    assert not out3["success"]
    assert "visual regression" in out3["error"]
    assert (tmp_path / "visual_form_diff.png").exists()
