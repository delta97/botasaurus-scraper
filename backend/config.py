"""Central paths and constants. All runtime data lives under data/ (gitignored)."""
import os
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", str(ROOT_DIR / "data")))
DB_PATH = DATA_DIR / "app.db"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"

MAX_AGENT_STEPS = 25
SNAPSHOT_CHAR_BUDGET = 6000
MAX_INTERACTIVE_ELEMENTS = 80

# Botasaurus does not download Chrome on Linux; it must be on PATH.
CHROME_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "google-chrome-beta",
    "chrome",
]

DEFAULT_BOTASAURUS_CONFIG = {
    "headless": True,
    "wait_for_complete_page_load": True,
    "block_images": False,
    "block_images_and_css": False,
    "bypass_cloudflare": False,
    "screenshots": True,
    "proxy": None,
    "user_agent": None,
    "window_size": None,
    "profile": None,
    "max_retry": 0,
    "output_format": "json",
    "enable_xvfb_virtual_display": False,
}


def find_chrome():
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
