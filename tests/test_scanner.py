"""Scanner tests — AC1 (inclusion set), AC2 (excluded dirs pruned),
AC8 (title extraction). Each test builds its own temp tree.
"""

from pathlib import Path

import scanner
from scanner import allowed_paths, scan


def _write(root: Path, rel: str, content: str = "x") -> None:
    """Create a file at root/rel, making parent dirs as needed."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# AC1: the scanner keeps exactly the docs worth serving and nothing else.
def test_scan_includes_exactly_the_right_files(tmp_path):
    # Build the AC1 fixture tree.
    _write(tmp_path, "docs/a.md")
    _write(tmp_path, "top.md")
    _write(tmp_path, "repoX/README.md")
    _write(tmp_path, "repoX/ARCHITECTURE.html")
    _write(tmp_path, "repoX/docs/guide.md")
    _write(tmp_path, "repoX/src/internal.md")  # buried source -> excluded
    _write(tmp_path, "repoX/node_modules/pkg/readme.md")  # excluded dir
    _write(tmp_path, "repoX/dist/out.html")  # excluded dir
    _write(tmp_path, ".hidden.md")  # dotfile -> excluded
    _write(tmp_path, "secret.txt")  # wrong extension -> excluded

    rel_paths = {e.rel_path for e in scan(tmp_path)}

    # The returned set must equal exactly the spec's expected set.
    assert rel_paths == {
        "docs/a.md",
        "top.md",
        "repoX/README.md",
        "repoX/ARCHITECTURE.html",
        "repoX/docs/guide.md",
    }


# AC2: excluded directory names are never descended into.
def test_excluded_dirs_are_never_descended(tmp_path):
    exclude = ["node_modules", ".git", "vendor", "__pycache__", ".venv"]
    # Each excluded dir holds a .md file that must NOT surface.
    for d in exclude:
        _write(tmp_path, f"{d}/buried.md")
    # A real doc so the scan isn't trivially empty.
    _write(tmp_path, "docs/real.md")

    entries = scan(tmp_path)

    # No returned entry may have a path segment inside the exclude set.
    excluded_set = set(exclude)
    for e in entries:
        segments = set(Path(e.rel_path).parts)
        assert segments.isdisjoint(excluded_set), e.rel_path
    # Sanity: the real doc did come through.
    assert {e.rel_path for e in entries} == {"docs/real.md"}


# AC8: titles come from the H1 (md), <title> (html), or filename fallback.
def test_titles_are_extracted_correctly(tmp_path):
    _write(tmp_path, "docs/h1.md", "# My Title\n\nbody\n")
    _write(tmp_path, "docs/notitle.md", "no heading here\n")
    _write(tmp_path, "docs/page.html", "<html><head><title>Page X</title></head></html>")

    titles = {e.rel_path: e.title for e in scan(tmp_path)}

    assert titles["docs/h1.md"] == "My Title"  # ATX H1
    assert titles["docs/notitle.md"] == "notitle.md"  # filename fallback
    assert titles["docs/page.html"] == "Page X"  # <title> contents


# allowed_paths (the path-safety validation set) covers exactly the same docs
# as scan(), but as resolved absolute paths and without reading file contents.
def test_allowed_paths_matches_scan_inclusion(tmp_path):
    _write(tmp_path, "docs/a.md")
    _write(tmp_path, "repoX/README.md")
    _write(tmp_path, "repoX/src/internal.md")  # buried source -> excluded
    _write(tmp_path, "secret.txt")  # wrong extension -> excluded

    scanner.clear_cache()
    paths = allowed_paths(tmp_path)

    # Exactly the resolved abs paths of the included docs — nothing buried/wrong.
    assert paths == {
        (tmp_path / "docs/a.md").resolve(),
        (tmp_path / "repoX/README.md").resolve(),
    }


# The scan is cached: a file added within the TTL window stays hidden until the
# cache is cleared. This is the contract the live server leans on — repeated
# walks are collapsed, and freshness is bounded by SCAN_CACHE_TTL.
def test_scan_is_cached_until_cleared(tmp_path):
    _write(tmp_path, "docs/a.md")

    scanner.clear_cache()
    assert {e.rel_path for e in scan(tmp_path)} == {"docs/a.md"}

    # New file appears on disk, but the cached result from above hides it.
    _write(tmp_path, "docs/b.md")
    assert {e.rel_path for e in scan(tmp_path)} == {"docs/a.md"}

    # Clearing the cache forces a fresh walk that sees both files.
    scanner.clear_cache()
    assert {e.rel_path for e in scan(tmp_path)} == {"docs/a.md", "docs/b.md"}
