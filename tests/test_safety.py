"""Path-safety tests — AC3. Uses an in-process server fixture on an
ephemeral port rooted at a temp tree; no dependency on real ~/projects.
"""

import urllib.request
from pathlib import Path


def _write(root: Path, rel: str, content: str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _status(url: str) -> int:
    """GET url and return the HTTP status, treating 4xx/5xx as a status too."""
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


# AC3: only allow-set docs resolve; non-docs and traversal are 403.
def test_path_safety_blocks_non_docs_and_traversal(serve, tmp_path):
    # Tree with a secret, a non-doc env file, and one valid doc.
    _write(tmp_path, "PGPASSWORD.txt", "hunter2")
    _write(tmp_path, "env/x.env", "SECRET=1")
    _write(tmp_path, "docs/a.md", "# A\n")

    base = serve(tmp_path)

    # Non-doc extension at root -> not in allow-set -> 403.
    assert _status(f"{base}/raw?path=PGPASSWORD.txt") == 403
    # Buried env file, wrong extension -> 403.
    assert _status(f"{base}/content?path=env/x.env") == 403
    # Directory traversal escaping root -> 403.
    assert _status(f"{base}/view?path=../../../../etc/passwd") == 403
    # The one real doc resolves -> 200.
    assert _status(f"{base}/raw?path=docs/a.md") == 200
