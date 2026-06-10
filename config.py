"""Single source of truth for the doc server's configuration.

scanner.py imports EXCLUDE_DIRS and ELIGIBLE_EXTENSIONS from here so the
scan rules live in exactly one place.

Two settings are environment-overridable so the server isn't pinned to one
machine's layout:
  DOC_SERVER_ROOT  directory the scanner walks    (default: ~/projects)
  DOC_SERVER_PORT  port the localhost server binds (default: 4848)
"""

import os
from pathlib import Path

# Port the localhost server binds to.
PORT = int(os.environ.get("DOC_SERVER_PORT", "4848"))

# Root that the scanner walks. Expanded to an absolute path so all downstream
# path-safety checks compare against a concrete resolved directory.
ROOT = Path(os.environ.get("DOC_SERVER_ROOT", Path.home() / "projects")).expanduser()

# Directory names pruned during the walk. These are never descended into.
# Any directory whose name additionally starts with "." is also pruned
# (handled in scanner.py, not enumerated here).
EXCLUDE_DIRS = frozenset(
    {
        "node_modules",
        "vendor",
        ".git",
        "dist",
        "build",
        "target",
        ".next",
        "out",
        "coverage",
        "__pycache__",
        "site-packages",
        ".venv",
        "venv",
        "env",
        "tmp",
        ".cache",
    }
)

# Only these file extensions are eligible to be served.
ELIGIBLE_EXTENSIONS = frozenset({".md", ".html"})

# Seconds a scan result is reused before the tree is walked again. The walk is
# the dominant per-request cost (it stats every file under ROOT), and a single
# doc open fires two validation walks (/view then the /content iframe), so a
# short TTL collapses those into one while keeping the index effectively live —
# a newly saved file appears within at most this many seconds.
SCAN_CACHE_TTL = 2.0

# The doc-server's own directory, resolved from this file's location. When the
# server is checked out inside ROOT, the scanner skips this directory so it
# never lists or serves its own source — regardless of the directory's name or
# how deep it sits.
SELF_DIR = Path(__file__).resolve().parent
