#!/usr/bin/env bash
#
# Install the doc server as a launchd LaunchAgent that runs at login.
# Idempotent: safe to re-run. Creates the venv, installs deps, writes the
# plist, and (re)bootstraps the agent for the current GUI session.
#
# Honors two optional environment variables, baked into the plist so the
# launchd-managed process (which does not inherit your shell environment) uses
# them too:
#   DOC_SERVER_ROOT  directory to serve    (default: ~/projects)
#   DOC_SERVER_PORT  port to bind          (default: 4848)
#
set -euo pipefail

# Resolve this script's directory so the install works regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LABEL="local.doc-server"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
VENV="$SCRIPT_DIR/.venv"
PY="$VENV/bin/python"
LOG="$SCRIPT_DIR/server.log"

ROOT="${DOC_SERVER_ROOT:-$HOME/projects}"
PORT="${DOC_SERVER_PORT:-4848}"

echo "==> Creating venv at $VENV"
if [ ! -x "$PY" ]; then
  python3 -m venv "$VENV"
fi

echo "==> Installing dependencies"
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo "==> Writing LaunchAgent plist at $PLIST"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PY}</string>
        <string>${SCRIPT_DIR}/server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>DOC_SERVER_ROOT</key>
        <string>${ROOT}</string>
        <key>DOC_SERVER_PORT</key>
        <string>${PORT}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG}</string>
    <key>StandardErrorPath</key>
    <string>${LOG}</string>
</dict>
</plist>
PLIST_EOF

# Validate the plist before loading it.
plutil -lint "$PLIST" >/dev/null

DOMAIN="gui/$(id -u)"

# Bootout first if already loaded (idempotent re-runs pick up plist changes),
# ignoring the "not loaded" error on a clean machine.
if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  echo "==> Booting out existing agent"
  launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
fi

echo "==> Bootstrapping agent into ${DOMAIN}"
launchctl bootstrap "${DOMAIN}" "$PLIST"

echo "==> Done. Doc server running at http://localhost:${PORT}"
echo "    Serving: ${ROOT}"
echo "    Restart with: launchctl kickstart -k ${DOMAIN}/${LABEL}"
