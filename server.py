"""stdlib ThreadingHTTPServer hosting the docs.

Routes:
  GET /                       -> index (live scan, collapsible tree)
  GET /view?path=<rel>        -> iframe shell (sticky header + breadcrumb)
  GET /content?path=<rel>     -> rendered markdown HTML or raw HTML bytes
  GET /raw?path=<rel>         -> raw file bytes with content-type
  GET /static/app.css         -> stylesheet
  anything else               -> 404

Path safety (for /view, /content, /raw):
  1. path param required.
  2. target = (ROOT / path).resolve() must be within ROOT.resolve().
  3. target must be a member of the current scan(ROOT) allow-set
     (compared by resolved abs path); otherwise 403.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import PORT, ROOT
from renderer import render_markdown
from scanner import allowed_paths, scan
import templates

# Content types for raw byte serving by extension.
_RAW_CONTENT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}


class SafetyError(Exception):
    """Raised when a path fails any of the three safety checks. Always 403."""


def resolve_safe(path_param: str | None, root: Path) -> Path:
    """Resolve `path_param` under `root` and enforce the three safety checks.

    Returns the resolved absolute path on success; raises SafetyError on any
    failure (missing param, traversal/symlink escape, or not in allow-set).
    """
    if not path_param:
        raise SafetyError("missing path")

    root_resolved = root.resolve()
    target = (root_resolved / path_param).resolve()

    # Prefix check on resolved paths defeats ../ traversal and symlink escape.
    if root_resolved != target and root_resolved not in target.parents:
        raise SafetyError("outside root")

    # Must be a doc the scanner would actually serve.
    if target not in allowed_paths(root):
        raise SafetyError("not an allowed doc")

    return target


class Handler(BaseHTTPRequestHandler):
    server_version = "DocServer/1.0"

    # ---- response helpers -------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_text(self, status: int, text: str, content_type: str) -> None:
        self._send(status, text.encode("utf-8"), content_type)

    def _error(self, status: int, message: str) -> None:
        self._send_text(status, message, "text/plain; charset=utf-8")

    # ---- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        parsed = urlparse(self.path)
        route = parsed.path
        params = parse_qs(parsed.query)

        try:
            if route == "/":
                self._handle_index()
            elif route == "/view":
                self._handle_view(params)
            elif route == "/content":
                self._handle_content(params)
            elif route == "/raw":
                self._handle_raw(params)
            elif route == "/static/app.css":
                self._send_text(200, templates.APP_CSS, "text/css; charset=utf-8")
            else:
                self._error(404, "Not Found")
        except SafetyError:
            self._error(403, "Forbidden")
        except BrokenPipeError:
            pass

    def _path_param(self, params: dict[str, list[str]]) -> str | None:
        values = params.get("path")
        return values[0] if values else None

    def _handle_index(self) -> None:
        # render_index builds the collapsible tree from the flat scan itself.
        html = templates.render_index(scan(ROOT))
        self._send_text(200, html, "text/html; charset=utf-8")

    def _handle_view(self, params: dict[str, list[str]]) -> None:
        path_param = self._path_param(params)
        # Enforce safety so /view can't shell out a frame to a non-doc.
        resolve_safe(path_param, ROOT)
        html = templates.render_view(path_param)
        self._send_text(200, html, "text/html; charset=utf-8")

    def _handle_content(self, params: dict[str, list[str]]) -> None:
        target = resolve_safe(self._path_param(params), ROOT)
        if target.suffix.lower() == ".md":
            html = render_markdown(target.read_text(encoding="utf-8", errors="replace"))
            self._send_text(200, html, "text/html; charset=utf-8")
        else:
            # HTML docs are streamed byte-for-byte, no rewrap.
            self._send(200, target.read_bytes(), "text/html; charset=utf-8")

    def _handle_raw(self, params: dict[str, list[str]]) -> None:
        target = resolve_safe(self._path_param(params), ROOT)
        content_type = _RAW_CONTENT_TYPES.get(
            target.suffix.lower(), "application/octet-stream"
        )
        self._send(200, target.read_bytes(), content_type)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Quiet, single-line logs to stderr (captured by launchd into server.log).
        super().log_message(format, *args)


def make_server(port: int = PORT) -> ThreadingHTTPServer:
    """Build a ThreadingHTTPServer. port=0 picks an ephemeral port (tests)."""
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    httpd = make_server(PORT)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
