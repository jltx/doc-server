"""Pure scanner: walk ROOT, keep only docs worth viewing/sharing.

The only I/O is reading the filesystem (directory walk + reading the first
bytes of a file for title extraction). `scan(root)` returns a list of
DocEntry and has no other side effects.

Inclusion rules (a file is kept if ANY is true):
  1. It lives under <root>/docs/**       (top-level docs dir, any depth)
  2. It is a loose top-level file:        <root>/*.md  or  <root>/*.html
  3. It is at a repo root:                <root>/<repo>/*.md or *.html
  4. It lives in a repo's docs folder:    <root>/<repo>/**/docs/**

Exclusions:
  - directories in EXCLUDE_DIRS, plus any dir whose name starts with "."
  - non-.md/.html files
  - dotfiles (e.g. ".foo.md")
  - the doc-server's own directory
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from config import ELIGIBLE_EXTENSIONS, EXCLUDE_DIRS, SCAN_CACHE_TTL, SELF_DIR

TOP_LEVEL_LABEL = "(top-level)"

# ATX H1: a line that begins with a single "#" followed by whitespace.
_H1_RE = re.compile(r"^#\s+(.+)$")
# First <title>...</title>, case-insensitive, across newlines.
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# A doc title (md H1 or html <title>) lives near the top of the file, so we read
# at most this many bytes to find it instead of pulling the whole file into
# memory — the difference is multiple MB across the tree on every full scan.
_TITLE_SCAN_BYTES = 65536


@dataclass
class DocEntry:
    abs_path: Path
    rel_path: str  # POSIX-style, relative to root
    repo: str  # first path segment under root, or "(top-level)"
    kind: str  # "md" or "html"
    title: str
    mtime: float  # epoch seconds


def _is_excluded_dir(name: str) -> bool:
    """A directory is pruned if it's in the exclude set or starts with a dot."""
    return name in EXCLUDE_DIRS or name.startswith(".")


def _should_include(rel_parts: tuple[str, ...]) -> bool:
    """Decide inclusion from the path segments relative to root.

    rel_parts includes the filename as the last segment.
    """
    # Rule 2: loose top-level file (exactly one segment = the filename).
    if len(rel_parts) == 1:
        return True

    dir_parts = rel_parts[:-1]

    # Rule 1: under top-level docs/ at any depth.
    if dir_parts and dir_parts[0] == "docs":
        return True

    # Rule 3: repo root file (exactly <repo>/<file> = two segments).
    if len(rel_parts) == 2:
        return True

    # Rule 4: inside any docs/ folder nested under a repo.
    if "docs" in dir_parts:
        return True

    return False


def title_for(path: Path) -> str:
    """Extract a display title for a doc, falling back to the filename.

    markdown: first ATX H1 line ("# Title"); else filename.
    html: text inside the first <title>...</title>; else filename.
    """
    suffix = path.suffix.lower()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            text = f.read(_TITLE_SCAN_BYTES)
    except OSError:
        return path.name

    if suffix == ".md":
        for line in text.splitlines():
            m = _H1_RE.match(line)
            if m:
                return m.group(1).strip()
        return path.name

    if suffix == ".html":
        m = _TITLE_RE.search(text)
        if m:
            return m.group(1).strip()
        return path.name

    return path.name


def _iter_included_files(root: Path):
    """Yield every file under `root` that passes the inclusion rules.

    `root` must already be resolved: the walk never follows directory symlinks,
    so every yielded path is a real path without further resolve() calls.
    """
    self_dir = str(SELF_DIR)

    # os.scandir reads the file type from the directory entry itself, so the
    # walk costs one syscall per directory instead of several per entry.
    def walk(directory: str):
        try:
            with os.scandir(directory) as it:
                children = sorted(it, key=lambda e: e.name)
        except OSError:
            return

        for child in children:
            name = child.name
            # Don't follow directory symlinks: a cycle would recurse forever,
            # and anything they point to outside the root is rejected by the
            # path-safety check anyway.
            if child.is_dir(follow_symlinks=False):
                if _is_excluded_dir(name) or child.path == self_dir:
                    continue
                yield from walk(child.path)
            elif (
                not name.startswith(".")
                and os.path.splitext(name)[1].lower() in ELIGIBLE_EXTENSIONS
                and child.is_file()
            ):
                path = Path(child.path)
                if _should_include(path.relative_to(root).parts):
                    yield path

    if root.is_dir():
        yield from walk(str(root))


def is_servable(target: Path, root: Path) -> bool:
    """Whether the walk under `root` would yield `target`, without walking.

    Both paths must be resolved. Path safety calls this once per request, so a
    doc open costs a few stats instead of a full tree walk.
    """
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        return False
    if not parts or not target.is_file():
        return False
    name = parts[-1]
    if name.startswith(".") or target.suffix.lower() not in ELIGIBLE_EXTENSIONS:
        return False
    if any(_is_excluded_dir(d) for d in parts[:-1]):
        return False
    if SELF_DIR == target or SELF_DIR in target.parents:
        return False
    return _should_include(parts)


def _build_scan(root: Path) -> list[DocEntry]:
    """Uncached: walk `root` and build a DocEntry (with title) per included doc."""
    entries: list[DocEntry] = []
    titles: dict[Path, tuple[float, str]] = {}
    for file in _iter_included_files(root):
        rel_parts = file.relative_to(root).parts
        repo = TOP_LEVEL_LABEL if len(rel_parts) == 1 else rel_parts[0]
        kind = "md" if file.suffix.lower() == ".md" else "html"
        mtime = file.stat().st_mtime
        titles[file] = (mtime, _cached_title(file, mtime))
        entries.append(
            DocEntry(
                abs_path=file,
                rel_path=file.relative_to(root).as_posix(),
                repo=repo,
                kind=kind,
                title=titles[file][1],
                mtime=mtime,
            )
        )
    # Swap in only this scan's files so titles of deleted docs don't accumulate.
    global _titles
    _titles = titles
    return entries


# Titles from the previous scan, keyed by path and checked against mtime, so a
# rescan reads only the docs that changed instead of opening every doc again.
_titles: dict[Path, tuple[float, str]] = {}


def _cached_title(file: Path, mtime: float) -> str:
    hit = _titles.get(file)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    return title_for(file)


# ---- TTL cache ------------------------------------------------------------
# The walk visits every directory under ROOT and is the dominant cost of an index
# load. We cache per (kind, resolved root) for SCAN_CACHE_TTL seconds. The
# lock guards only the dict; the walk runs outside it, so a burst of concurrent
# misses may walk more than once (harmless) rather than serialize behind a lock.
_cache_lock = threading.Lock()
# (kind, resolved root) -> (monotonic timestamp, value)
_cache: dict[tuple[str, Path], tuple[float, object]] = {}


def clear_cache() -> None:
    """Drop all cached results. Mainly for tests that mutate a tree in place."""
    with _cache_lock:
        _cache.clear()


def _cached(kind: str, root: Path, build):
    """Return build(root) for (kind, root), reusing a result within the TTL."""
    root = Path(root).resolve()
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get((kind, root))
        if hit is not None and (now - hit[0]) < SCAN_CACHE_TTL:
            return hit[1]

    value = build(root)

    with _cache_lock:
        _cache[(kind, root)] = (time.monotonic(), value)
    return value


def scan(root: Path) -> list[DocEntry]:
    """Return the docs worth serving under `root`, as DocEntry objects.

    Reads a title per changed doc, so this is the index's view of the tree.
    Cached for SCAN_CACHE_TTL seconds. Path-safety validation uses is_servable
    instead, which checks one path without a walk.
    """
    return _cached("scan", root, _build_scan)
