"""Shared test fixtures.

Tests are hermetic: each builds its own temp directory tree and runs an
in-process server on an ephemeral port pointed at that tree. Nothing here
depends on the real ~/projects contents or the launchd-installed server.
"""

import sys
import threading
from pathlib import Path

import pytest

# Make the package modules importable when pytest is run from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


@pytest.fixture
def serve(monkeypatch):
    """Start an in-process server rooted at a given directory.

    Usage:
        base = serve(tmp_path)   # -> "http://127.0.0.1:<ephemeral>"
    The server reads server.ROOT module-globally, so we point it at the temp
    root for the duration of the test and tear it down afterward.
    """
    httpd_holder = {}

    def _start(root: Path) -> str:
        monkeypatch.setattr(server, "ROOT", Path(root).resolve())
        httpd = server.make_server(port=0)  # ephemeral port
        httpd_holder["httpd"] = httpd
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        httpd_holder["thread"] = thread
        host, port = httpd.server_address
        return f"http://{host}:{port}"

    yield _start

    httpd = httpd_holder.get("httpd")
    if httpd is not None:
        httpd.shutdown()
        httpd.server_close()
        httpd_holder["thread"].join(timeout=5)
