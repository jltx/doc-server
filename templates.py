"""String templates: the index page, the /view iframe shell, and the
stylesheet served at /static/app.css. No build step, no framework.
"""

from __future__ import annotations

import datetime
import html
from urllib.parse import quote


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _fmt_mtime(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Theme (light/dark) — shared across the index, the /view shell, and the
# rendered-markdown page (renderer.py imports THEME_INIT). Dark is the default.
# ---------------------------------------------------------------------------

# Runs in <head> before paint so there's no light-mode flash on load.
THEME_INIT = (
    "<script>(function(){var t;try{t=localStorage.getItem('docserver-theme');}"
    "catch(e){}document.documentElement.setAttribute('data-theme',t||'dark');})();"
    "</script>"
)

# The toggle control; styled via .theme-toggle, glyph set by THEME_TOGGLE_SCRIPT.
THEME_BUTTON = (
    '<button id="theme-toggle" class="theme-toggle" type="button" '
    'title="Toggle light/dark"></button>'
)

# Flips + persists the theme, updates the button glyph, and (on the /view
# shell) syncs the rendered-markdown iframe live without a reload.
THEME_TOGGLE_SCRIPT = """
<script>
(function () {
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  function cur() { return document.documentElement.getAttribute('data-theme') || 'dark'; }
  function glyph(t) { btn.textContent = t === 'dark' ? '☀' : '☾'; }
  glyph(cur());
  btn.addEventListener('click', function () {
    var next = cur() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('docserver-theme', next); } catch (e) {}
    glyph(next);
    var fr = document.querySelector('.view-frame');
    if (fr) {
      try {
        var d = fr.contentDocument;
        if (d && d.querySelector('.markdown-body')) {
          d.documentElement.setAttribute('data-theme', next);
        }
      } catch (e) {}
    }
  });
})();
</script>
"""


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

_INDEX_HEAD = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Docs</title>
<link rel="stylesheet" href="/static/app.css">
{THEME_INIT}
</head>
<body class="index-body">
<div class="topbar"><h1>Docs</h1>{THEME_BUTTON}</div>
<input id="filter" type="text" placeholder="Filter by title or path..." autofocus>
"""

# Inline filter: hides any .doc-row whose data-haystack doesn't contain the
# (lowercased) query. While filtering, folders auto-expand if they contain a
# match and hide if they don't; clearing the box restores the default collapsed
# state (docs stays open via its data-default-open marker).
_INDEX_TAIL = """
<script>
(function () {
  var input = document.getElementById('filter');
  var rows = Array.prototype.slice.call(document.querySelectorAll('.doc-row'));
  var folders = Array.prototype.slice.call(document.querySelectorAll('.tree-folder'));
  function apply(q) {
    q = (q || '').toLowerCase();
    var filtering = q.length > 0;
    rows.forEach(function (row) {
      var hay = row.getAttribute('data-haystack');
      row.style.display = hay.indexOf(q) === -1 ? 'none' : '';
    });
    folders.forEach(function (f) {
      var hasMatch = f.querySelectorAll('.doc-row:not([style*="none"])').length > 0;
      f.style.display = (filtering && !hasMatch) ? 'none' : '';
      f.open = filtering ? hasMatch : f.hasAttribute('data-default-open');
    });
  }
  input.addEventListener('input', function () { apply(input.value); });
  // Honor ?filter=<segment> deep links from breadcrumb folder segments.
  var params = new URLSearchParams(window.location.search);
  var initial = params.get('filter');
  if (initial) { input.value = initial; apply(initial); }
})();
</script>
""" + THEME_TOGGLE_SCRIPT + """</body>
</html>
"""


class _Dir:
    """A directory node in the index tree: named child dirs + leaf files."""

    __slots__ = ("name", "dirs", "files")

    def __init__(self, name: str) -> None:
        self.name = name
        self.dirs: dict[str, _Dir] = {}
        self.files: list = []


def _build_tree(entries: list) -> _Dir:
    """Nest a flat list of DocEntry into a directory tree keyed by rel_path."""
    root = _Dir("")
    for e in entries:
        *dir_segs, _fname = e.rel_path.split("/")
        node = root
        for seg in dir_segs:
            node = node.dirs.setdefault(seg, _Dir(seg))
        node.files.append(e)
    return root


def _count_docs(node: _Dir) -> int:
    """Total docs at or below this directory (for the folder count badge)."""
    return len(node.files) + sum(_count_docs(d) for d in node.dirs.values())


def _render_file(e) -> str:
    href = "/view?path=" + quote(e.rel_path)
    haystack = (e.title + " " + e.rel_path).lower()
    return (
        '<a class="doc-row" href="%s" data-haystack="%s">'
        '<span class="doc-name">%s</span>'
        '<span class="meta">%s</span>'
        "</a>"
        % (_esc(href), _esc(haystack), _esc(e.title), _esc(_fmt_mtime(e.mtime)))
    )


def _render_dir(node: _Dir, *, default_open: bool = False) -> str:
    # default_open also gets a marker attr so the filter JS can restore state.
    attrs = " open data-default-open" if default_open else ""
    return (
        '<details class="tree-folder"%s>'
        '<summary>%s/ <span class="count">%d</span></summary>'
        '<div class="tree-children">%s</div>'
        "</details>"
        % (attrs, _esc(node.name), _count_docs(node), _render_children(node))
    )


def _render_children(node: _Dir) -> str:
    # Folders first (alphabetical), then files (newest first) at this level.
    parts = [_render_dir(node.dirs[name]) for name in sorted(node.dirs)]
    parts += [
        _render_file(e)
        for e in sorted(node.files, key=lambda e: e.mtime, reverse=True)
    ]
    return "".join(parts)


def render_index(entries: list) -> str:
    """Render the index as a collapsible tree.

    `entries` is the flat list of DocEntry from scan(). Only root-level folders
    and loose root files show by default; clicking a folder expands it. The
    ~/projects/docs folder is pinned to the top and expanded by default.
    """
    root = _build_tree(entries)
    parts = [_INDEX_HEAD, '<div class="tree">']
    docs = root.dirs.pop("docs", None)
    if docs is not None:
        parts.append(_render_dir(docs, default_open=True))
    parts += [_render_dir(root.dirs[name]) for name in sorted(root.dirs)]
    parts += [
        _render_file(e)
        for e in sorted(root.files, key=lambda e: e.mtime, reverse=True)
    ]
    parts.append("</div>")
    parts.append(_INDEX_TAIL)
    return "".join(parts)


# ---------------------------------------------------------------------------
# /view iframe shell
# ---------------------------------------------------------------------------

_VIEW = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/static/app.css">
{theme_init}
</head>
<body class="view-body">
<header class="view-header">
  <a class="back" href="#" onclick="history.back(); return false;">&larr; Back</a>
  <nav class="breadcrumb">{breadcrumb}</nav>
  <a class="home" href="/">Home</a>
  {theme_button}
</header>
<iframe class="view-frame" src="/content?path={content_path}"></iframe>
{theme_toggle}
</body>
</html>
"""


def _build_breadcrumb(rel_path: str) -> str:
    """Folder segments link to /?filter=<segment>; the filename is plain text."""
    segments = rel_path.split("/")
    crumbs = []
    for i, seg in enumerate(segments):
        is_last = i == len(segments) - 1
        if is_last:
            crumbs.append('<span class="crumb file">%s</span>' % _esc(seg))
        else:
            href = "/?filter=" + quote(seg)
            crumbs.append('<a class="crumb" href="%s">%s</a>' % (_esc(href), _esc(seg)))
    return '<span class="sep">/</span>'.join(crumbs)


def render_view(rel_path: str) -> str:
    """Render the iframe shell for a doc at `rel_path`."""
    return _VIEW.format(
        title=_esc(rel_path),
        breadcrumb=_build_breadcrumb(rel_path),
        content_path=quote(rel_path),
        theme_init=THEME_INIT,
        theme_button=THEME_BUTTON,
        theme_toggle=THEME_TOGGLE_SCRIPT,
    )


# ---------------------------------------------------------------------------
# Stylesheet (/static/app.css)
# ---------------------------------------------------------------------------

HEADER_HEIGHT = "48px"

APP_CSS = """
:root {
  --header-height: %s;
  /* dark (default) */
  --bg: #0d1117;
  --fg: #c9d1d9;
  --muted: #8b949e;
  --border: #30363d;
  --link: #58a6ff;
  --surface: #161b22;
  --code-bg: #161b22;
  --syn-k: #ff7b72;
  --syn-s: #a5d6ff;
  --syn-c: #8b949e;
  --syn-nb: #ffa657;
  --syn-nf: #d2a8ff;
  --syn-mi: #79c0ff;
}
html[data-theme="light"] {
  --bg: #ffffff;
  --fg: #24292f;
  --muted: #57606a;
  --border: #d0d7de;
  --link: #0969da;
  --surface: #f6f8fa;
  --code-bg: #f6f8fa;
  --syn-k: #cf222e;
  --syn-s: #0a3069;
  --syn-c: #6e7781;
  --syn-nb: #6639ba;
  --syn-nf: #8250df;
  --syn-mi: #0550ae;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  color: var(--fg);
  background: var(--bg);
  line-height: 1.5;
}

/* ---- index ---- */
.index-body { max-width: 980px; margin: 0 auto; padding: 24px; }
.index-body h1 { margin-top: 0; }
.topbar { display: flex; align-items: center; justify-content: space-between; }
.topbar h1 { margin: 0; }
.theme-toggle {
  cursor: pointer;
  width: 32px;
  height: 32px;
  font-size: 15px;
  line-height: 1;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--fg);
}
.theme-toggle:hover { border-color: var(--link); }
.view-header .theme-toggle { width: 28px; height: 28px; font-size: 14px; }
#filter {
  width: 100%%;
  padding: 8px 12px;
  font-size: 15px;
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 24px;
}
.tree { margin-top: 4px; }
.tree-folder { margin: 1px 0; }
.tree-folder > summary {
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 6px;
  font-weight: 600;
  user-select: none;
}
.tree-folder > summary:hover { background: var(--surface); }
.tree-folder .count { color: var(--muted); font-weight: 400; font-size: 12px; margin-left: 4px; }
.tree-children { margin-left: 16px; border-left: 1px solid var(--border); padding-left: 8px; }
.doc-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 3px 6px;
  border-radius: 6px;
  color: var(--link);
  text-decoration: none;
}
.doc-row:hover { background: var(--surface); }
.doc-row:hover .doc-name { text-decoration: underline; }
.doc-row .meta { color: var(--muted); font-size: 12px; margin-left: auto; }

/* ---- /view shell ---- */
.view-body { height: 100vh; overflow: hidden; }
.view-header {
  position: sticky;
  top: 0;
  height: var(--header-height);
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.view-header a { color: var(--link); text-decoration: none; }
.view-header a:hover { text-decoration: underline; }
.breadcrumb { flex: 1; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.breadcrumb .sep { color: var(--muted); margin: 0 6px; }
.breadcrumb .file { color: var(--fg); font-weight: 600; }
.view-frame {
  display: block;
  border: 0;
  width: 100%%;
  height: calc(100vh - var(--header-height));
}

/* ---- rendered markdown ---- */
.markdown-body { max-width: 900px; margin: 0 auto; padding: 32px; }
.markdown-body h1, .markdown-body h2 { border-bottom: 1px solid var(--border); padding-bottom: .3em; }
.markdown-body table { border-collapse: collapse; }
.markdown-body table th, .markdown-body table td { border: 1px solid var(--border); padding: 6px 13px; }
.markdown-body code {
  background: rgba(175,184,193,.2);
  padding: .2em .4em;
  border-radius: 6px;
  font-size: 85%%;
}
.markdown-body pre code { background: transparent; padding: 0; }

/* ---- Pygments (codehilite) ---- */
.codehilite {
  background: var(--code-bg);
  border-radius: 6px;
  padding: 12px 16px;
  overflow: auto;
}
.codehilite pre { margin: 0; }
.codehilite .k { color: var(--syn-k); }
.codehilite .s, .codehilite .s1, .codehilite .s2 { color: var(--syn-s); }
.codehilite .c, .codehilite .c1, .codehilite .cm { color: var(--syn-c); font-style: italic; }
.codehilite .nb { color: var(--syn-nb); }
.codehilite .nf { color: var(--syn-nf); }
.codehilite .mi, .codehilite .mf { color: var(--syn-mi); }
""" % (HEADER_HEIGHT,)
