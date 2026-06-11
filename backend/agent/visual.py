"""Pixel-diff comparison for visual regression (assert_screenshot steps).

A pixel counts as "different" when any RGB channel differs by more than
NOISE_TOLERANCE — this absorbs antialiasing jitter between renders. The check
passes when the fraction of different pixels is <= threshold.
"""
import os

from PIL import Image, ImageChops

NOISE_TOLERANCE = 16  # per-channel 0-255
DEFAULT_THRESHOLD = 0.01  # 1% of pixels may differ


def compare_images(baseline_path, current_path, diff_path=None,
                   threshold=DEFAULT_THRESHOLD):
    """Returns (passed: bool, diff_ratio: float, message: str). When the check
    fails and diff_path is given, writes a visualization image where differing
    pixels are highlighted in red over a dimmed baseline."""
    baseline = Image.open(baseline_path).convert("RGB")
    current = Image.open(current_path).convert("RGB")

    if baseline.size != current.size:
        return False, 1.0, (f"size mismatch: baseline {baseline.size[0]}x{baseline.size[1]} "
                            f"vs current {current.size[0]}x{current.size[1]}")

    diff = ImageChops.difference(baseline, current)
    # max channel delta per pixel, thresholded against noise
    mask = diff.convert("L").point(lambda v: 255 if v > NOISE_TOLERANCE else 0)
    histogram = mask.histogram()
    changed = sum(histogram[1:])
    total = baseline.size[0] * baseline.size[1]
    ratio = changed / total if total else 0.0

    if ratio <= threshold:
        return True, ratio, f"{ratio:.4%} pixels differ (threshold {threshold:.2%})"

    if diff_path:
        os.makedirs(os.path.dirname(diff_path) or ".", exist_ok=True)
        dimmed = Image.blend(baseline, Image.new("RGB", baseline.size, (0, 0, 0)), 0.6)
        red = Image.new("RGB", baseline.size, (255, 40, 40))
        visual = Image.composite(red, dimmed, mask)
        visual.save(diff_path)
    return False, ratio, (f"{ratio:.4%} pixels differ (threshold {threshold:.2%})"
                          + (f"; diff image: {diff_path}" if diff_path else ""))
