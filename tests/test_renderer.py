"""Renderer / content tests — AC4 (markdown -> highlighted HTML),
AC5 (HTML served byte-for-byte), plus the AC7 parser-based assertion that
the /view shell has all breadcrumb segments and a history.back() control.

Uses the in-process server fixture on an ephemeral port rooted at a temp tree.
"""

import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from renderer import render_markdown


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _get(url: str):
    """GET url; return (status, content_type, body_bytes)."""
    with urllib.request.urlopen(url) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read()


# AC4: markdown renders with an H1, a table, and a Pygments highlight wrapper.
def test_markdown_renders_with_highlighted_code(serve, tmp_path):
    md = (
        "# Heading\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "```python\ndef f():\n    return 1\n```\n"
    )
    _write(tmp_path, "docs/sample.md", md)

    base = serve(tmp_path)
    status, ctype, body = _get(f"{base}/content?path=docs/sample.md")
    text = body.decode("utf-8")

    assert status == 200
    assert ctype == "text/html; charset=utf-8"
    assert "<h1" in text  # heading rendered
    assert "<table" in text  # table rendered (extra extension)
    assert 'class="codehilite"' in text  # Pygments wrapper (codehilite)


# Unit-level guard that render_markdown alone produces the highlight wrapper.
def test_render_markdown_unit_produces_codehilite():
    out = render_markdown("```python\nx = 1\n```\n")
    assert 'class="codehilite"' in out


# The renderer reuses one Markdown instance per thread and calls reset() between
# conversions. Guard that reset() actually clears state — no content from a
# prior render bleeds into the next.
def test_render_markdown_has_no_state_bleed_across_calls():
    first = render_markdown("# First\n")
    second = render_markdown("# Second\n")

    assert "First" in first
    assert "Second" in second
    assert "First" not in second  # prior conversion left no residue


# AC5: HTML docs are streamed byte-for-byte, no header injection or rewrap.
def test_html_served_byte_for_byte(serve, tmp_path):
    raw = (
        "<!DOCTYPE html><html><head><title>Foo</title></head>"
        "<body><h1>Self-contained</h1><p>unchanged</p></body></html>"
    )
    _write(tmp_path, "docs/foo.html", raw)
    on_disk = (tmp_path / "docs/foo.html").read_bytes()

    base = serve(tmp_path)
    status, _ctype, body = _get(f"{base}/content?path=docs/foo.html")

    assert status == 200
    assert body == on_disk  # identical bytes


# AC7: /view shell parser assertion — all three breadcrumb segments present,
# an <iframe> with the right src, and a history.back() Back control.
class _ViewParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_header = False
        self.has_iframe = False
        self.iframe_src = None
        self.back_onclick = None
        self._in_a = False
        self._cur_attrs = {}
        self.text_chunks = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "header":
            self.has_header = True
        elif tag == "iframe":
            self.has_iframe = True
            self.iframe_src = d.get("src")
        elif tag == "a":
            self._in_a = True
            self._cur_attrs = d
            if "back" in (d.get("class") or ""):
                self.back_onclick = d.get("onclick")

    def handle_endtag(self, tag):
        if tag == "a":
            self._in_a = False

    def handle_data(self, data):
        self.text_chunks.append(data)


def test_view_shell_has_breadcrumb_back_and_iframe(serve, tmp_path):
    rel = "social-v1/docs/conventions.md"
    _write(tmp_path, rel, "# Conventions\n")

    base = serve(tmp_path)
    _status, _ctype, body = _get(f"{base}/view?path={rel}")
    html = body.decode("utf-8")

    parser = _ViewParser()
    parser.feed(html)
    joined_text = "".join(parser.text_chunks)

    # Header element present.
    assert parser.has_header
    # All three breadcrumb segments appear as text, in order.
    assert "social-v1" in joined_text
    assert "docs" in joined_text
    assert "conventions.md" in joined_text
    i_repo = joined_text.index("social-v1")
    i_docs = joined_text.index("docs", i_repo)
    i_file = joined_text.index("conventions.md", i_docs)
    assert i_repo < i_docs < i_file
    # Back control invokes history.back().
    assert parser.back_onclick is not None
    assert "history.back()" in parser.back_onclick
    # iframe points at the content route for this doc.
    assert parser.has_iframe
    assert parser.iframe_src == f"/content?path={rel}"
