"""Scanner tests — AC1 (inclusion set), AC2 (excluded dirs pruned),
AC8 (title extraction). Each test builds its own temp tree.
"""

from pathlib import Path

import scanner
from scanner import scan


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


# is_servable (the path-safety check) accepts exactly the docs scan() yields.
def test_is_servable_matches_scan_inclusion(tmp_path):
    root = tmp_path.resolve()
    _write(root, "docs/a.md")
    _write(root, "repoX/README.md")
    _write(root, "repoX/docs/deep/guide.md")
    _write(root, "repoX/src/internal.md")  # buried source -> excluded
    _write(root, "repoX/node_modules/pkg/docs/x.md")  # excluded dir
    _write(root, "repoX/.claude/docs/y.md")  # dot dir
    _write(root, "secret.txt")  # wrong extension -> excluded

    scanner.clear_cache()
    scanned = {e.abs_path for e in scan(root)}
    candidates = {p.resolve() for p in root.rglob("*") if p.is_file()}

    assert {p for p in candidates if scanner.is_servable(p, root)} == scanned


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


# Directory symlinks are not followed: a cycle would recurse forever, and any
# target outside the root is rejected by path safety anyway.
def test_symlinked_directory_is_not_followed(tmp_path):
    import os

    # A real docs tree the symlink will point at.
    target = tmp_path / "target_repo" / "docs"
    target.mkdir(parents=True)
    _write(target, "guide.md")
    # A directory symlink placed where the walk would otherwise descend.
    (tmp_path / "docs").mkdir(exist_ok=True)
    os.symlink(target, tmp_path / "docs" / "link")
    _write(tmp_path, "docs/real.md")

    scanner.clear_cache()
    rels = {e.rel_path for e in scan(tmp_path)}

    # The walk did not descend through the symlink (no "docs/link/..." entries).
    assert not any(r.startswith("docs/link/") for r in rels)
    # Real, non-symlinked docs still surface.
    assert "docs/real.md" in rels


# A rescan re-reads the title of a doc whose mtime changed.
def test_rescan_picks_up_changed_title(tmp_path):
    import os

    _write(tmp_path, "docs/a.md", "# Old\n")
    scanner.clear_cache()
    assert [e.title for e in scan(tmp_path)] == ["Old"]

    _write(tmp_path, "docs/a.md", "# New\n")
    st = (tmp_path / "docs/a.md").stat()
    os.utime(tmp_path / "docs/a.md", (st.st_atime, st.st_mtime + 1))
    scanner.clear_cache()
    assert [e.title for e in scan(tmp_path)] == ["New"]
