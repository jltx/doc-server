"""Markdown -> styled HTML. HTML docs are not rendered here; server.py
streams their bytes unchanged.
"""

from __future__ import annotations

import threading

import markdown

from templates import THEME_INIT

# Extensions per spec: extra (tables, fenced code), codehilite (Pygments),
# toc, sane_lists.
_EXTENSIONS = ["extra", "codehilite", "toc", "sane_lists"]

# codehilite emits <div class="codehilite">; we ship the Pygments stylesheet
# inline so highlighted code is styled without an external request. THEME_INIT
# applies the saved light/dark theme (default dark) before paint, matching the
# /view shell that frames this page.
_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static/app.css">
{theme_init}
</head>
<body class="markdown-body">
{content}
</body>
</html>
"""


# Building a Markdown instance registers every extension, which costs more than
# the conversion itself for typical docs. We reuse one instance per thread
# (the server is threaded, and Markdown instances are not thread-safe),
# calling reset() to clear per-conversion state. Output is byte-identical to a
# fresh instance; reuse just skips the repeated setup.
_local = threading.local()


def _markdown() -> markdown.Markdown:
    md = getattr(_local, "md", None)
    if md is None:
        md = markdown.Markdown(extensions=_EXTENSIONS, output_format="html5")
        _local.md = md
    return md


def render_markdown(text: str) -> str:
    """Render markdown source to a full styled HTML page.

    The fragment is wrapped in the content template, which links the
    GitHub-ish stylesheet served at /static/app.css.
    """
    md = _markdown()
    md.reset()
    fragment = md.convert(text)
    return _PAGE.format(theme_init=THEME_INIT, content=fragment)
