import http.server
import threading
from pathlib import Path

import pytest

from backend import config as app_config
from backend import db

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: needs Chrome (skipped when not installed)")


def pytest_collection_modifyitems(config, items):
    if app_config.find_chrome():
        return
    skip = pytest.mark.skip(reason="Chrome not installed")
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip)


@pytest.fixture()
def session_factory(tmp_path):
    return db.init_db(tmp_path / "test.db")


@pytest.fixture()
def form_page_html():
    return (FIXTURES / "form_page.html").read_text()


@pytest.fixture(scope="session")
def fixture_server():
    """Serve tests/fixtures over HTTP for browser-based tests."""
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(FIXTURES), **kw)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
