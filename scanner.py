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

    Shared by scan() and allowed_paths() so the prune/inclusion logic lives in
    one place. Yields raw Path objects; callers decide whether to read titles
    (scan) or just take the resolved path (allowed_paths).
    """
    # Manual recursive walk so we can prune excluded directories before
    # descending into them (os.walk-style topdown pruning).
    def walk(directory: Path):
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return

        for child in children:
            if child.is_dir():
                # Don't follow directory symlinks: a cycle would recurse
                # forever, and anything they point to outside the root is
                # rejected by the path-safety check anyway.
                if child.is_symlink():
                    continue
                name = child.name
                if _is_excluded_dir(name):
                    continue
                # Never descend into the doc-server's own directory, wherever
                # it sits under root, so the server doesn't serve its own source.
                if child.resolve() == SELF_DIR:
                    continue
                yield from walk(child)
            elif child.is_file():
                name = child.name
                # Dotfiles are excluded.
                if name.startswith("."):
                    continue
                if child.suffix.lower() not in ELIGIBLE_EXTENSIONS:
                    continue
                if _should_include(child.relative_to(root).parts):
                    yield child

    if root.is_dir():
        yield from walk(root)


def _build_scan(root: Path) -> list[DocEntry]:
    """Uncached: walk `root` and build a DocEntry (with title) per included doc."""
    entries: list[DocEntry] = []
    for file in _iter_included_files(root):
        rel_parts = file.relative_to(root).parts
        repo = TOP_LEVEL_LABEL if len(rel_parts) == 1 else rel_parts[0]
        kind = "md" if file.suffix.lower() == ".md" else "html"
        entries.append(
            DocEntry(
                abs_path=file.resolve(),
                rel_path=file.relative_to(root).as_posix(),
                repo=repo,
                kind=kind,
                title=title_for(file),
                mtime=file.stat().st_mtime,
            )
        )
    return entries


# ---- TTL cache ------------------------------------------------------------
# The walk stats every file under ROOT and is the dominant per-request cost, and
# a single doc open fires two path-safety walks (/view then the /content
# iframe). We cache per (kind, resolved root) for SCAN_CACHE_TTL seconds. The
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

    Reads a title per doc, so this is the index's view of the tree. Cached for
    SCAN_CACHE_TTL seconds. Path-safety validation should use allowed_paths
    instead, which skips the title reads.
    """
    return _cached("scan", root, _build_scan)


def allowed_paths(root: Path) -> set[Path]:
    """Resolved absolute paths of every doc the scanner would serve.

    This is all path-safety validation needs. Unlike scan() it reads no file
    contents — just the directory walk — so a cold doc open isn't taxed with
    title extraction it never uses.
    """
    return _cached(
        "paths",
        root,
        lambda r: {file.resolve() for file in _iter_included_files(r)},
    )
