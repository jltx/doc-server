# Doc Server

A localhost server that hosts the markdown and HTML docs scattered across a
projects tree so they can be browsed and shared from one place. It
auto-discovers docs on every page load (no registration step), can run
automatically at login via launchd, and frames every doc with a sticky header
(breadcrumb + back) that works for both rendered markdown and self-contained
HTML docs.

Default URL: **http://localhost:4848**

## What gets served

A single scanner walks the root directory (default `~/projects`) and keeps a
file only if it's a doc worth viewing/sharing — not generated output, not
third-party.

A file is included when any of these is true:

1. It lives under `<root>/docs/**` (any depth).
2. It's a loose top-level file: `<root>/*.md` or `<root>/*.html`.
3. It's at a repo root: `<root>/<repo>/*.md` or `<root>/<repo>/*.html`.
4. It lives inside a repo's own docs folder: `<root>/<repo>/**/docs/**`.

Pruned directories (never descended into): `node_modules`, `vendor`, `.git`,
`dist`, `build`, `target`, `.next`, `out`, `coverage`, `__pycache__`,
`site-packages`, `.venv`, `venv`, `env`, `tmp`, `.cache`, and any directory
whose name starts with `.`. Only `.md`/`.html` files are eligible; dotfiles and
the doc-server's own directory are excluded.

Drop a doc anywhere matching the include rules and it shows up within a couple
of seconds — no restart, no registration.

## The index

The index is a collapsible tree:

- Only root-level folders and loose root files show by default; click a folder
  (a native `<details>` disclosure) to expand its files and subfolders.
- Folders are sorted alphabetically; files are sorted by modified time, newest
  first. Each folder shows a count of the docs beneath it.
- The `docs/` folder is pinned to the top and expanded by default.
- A filter box narrows by title or path; matching branches auto-expand and
  non-matches hide, restoring the default state when cleared.

### Light / dark theme

A toggle in the top-right switches between light and dark; the choice persists
in `localStorage` and defaults to **dark**. The theme is applied before first
paint (no flash) and covers the chrome and rendered markdown, including syntax
highlighting. Self-contained HTML docs keep their own styling.

## Configuration

Most people just answer the folder prompt during `./install.sh`. For the port,
or for scripting the install non-interactively, two environment variables are
honored:

| Variable | Default | Meaning |
|---|---|---|
| `DOC_SERVER_ROOT` | `~/projects` | Directory the scanner walks. If set, it overrides the install prompt. |
| `DOC_SERVER_PORT` | `4848` | Port the localhost server binds to. |

`install.sh` bakes the chosen values into the LaunchAgent plist, so a
launchd-managed instance (which doesn't inherit your shell environment) honors
them too. To run ad hoc without launchd:

```
DOC_SERVER_ROOT=~/work DOC_SERVER_PORT=5000 ./.venv/bin/python server.py
```

## Layout

```
doc-server/
  config.py        # PORT, ROOT (env-overridable), exclude set, extensions
  scanner.py       # pure walk + filter -> list[DocEntry], TTL-cached
  renderer.py      # markdown -> styled HTML; html passed through raw
  templates.py     # index tree + /view iframe shell + theme + app.css
  server.py        # stdlib ThreadingHTTPServer; routes + path safety
  tests/           # hermetic pytest suite (own temp trees, ephemeral port)
  requirements.txt # markdown, pygments, pytest
  install.sh       # venv + deps + launchd LaunchAgent (idempotent)
```

## Routes

| Route | Returns |
|---|---|
| `GET /` | Index page: live scan, collapsible tree, filter, theme toggle. |
| `GET /view?path=<rel>` | iframe shell: sticky header (breadcrumb + Back + Home) + iframe. |
| `GET /content?path=<rel>` | Rendered markdown HTML, or raw HTML bytes. |
| `GET /raw?path=<rel>` | Raw file bytes with content-type. |
| `GET /static/app.css` | Stylesheet. |
| anything else | 404. |

### Path safety

`/view`, `/content`, and `/raw` enforce three checks: the `path` param must be
present, the resolved target must stay within the root (defeats `../` traversal
and symlink escapes), and the target must be a file the scan would include. A request for a non-doc such as `.env` or a secrets file returns
**403** even with a hand-crafted URL.

## Install (macOS)

1. **Get the code** — download this folder (GitHub → Code → Download ZIP, then
   unzip) or `git clone` it.
2. **Check for Python** — in Terminal, run `python3 --version` (need 3.8 or
   newer). If you see "command not found", install Apple's Command Line Tools
   (which include it): `xcode-select --install`, then continue.
3. **Run the installer** — in Terminal:

   ```
   cd doc-server
   ./install.sh
   ```

   It asks **which folder to serve** — press Enter for `~/projects`, or type a
   path (e.g. `~/Documents/notes`). That's it: the server starts immediately
   and again every time you log in.

Open **http://localhost:4848**.

To **change the folder later**, just re-run `./install.sh` and answer the
prompt again.

Under the hood, `install.sh` creates a `.venv`, installs `markdown` +
`pygments` + `pytest`, writes a LaunchAgent at
`~/Library/LaunchAgents/local.doc-server.plist` (`RunAtLoad` + `KeepAlive`,
plus `ProcessType: Interactive` so launchd does not throttle its disk walks),
and bootstraps it into `gui/$UID`. It's idempotent — re-running boots out the
existing agent first and reloads.

Restart it any time with:

```
launchctl kickstart -k gui/$UID/local.doc-server
```

Logs are written next to the source as `server.log`.

## Run without installing

```
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python server.py
```

## Tests

```
./.venv/bin/python -m pytest -q
```

The suite is hermetic: each test builds its own temp directory tree and runs an
in-process server on an ephemeral port. Nothing depends on the real root
contents or the launchd-installed server.

## Out of scope

No file watcher / live auto-refresh (a reload reflects new files within the
scan-cache TTL), no full-text body search (client-side title/path filter only),
no auth (localhost only).

## License

MIT — see [LICENSE](LICENSE).
