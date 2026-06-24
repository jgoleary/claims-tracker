#!/bin/bash
# Self-contained installer for Claims Tracker (macOS).
# Run via:  bash deploy/install.sh      (NOT ./install.sh, NOT a Finder double-click)
# Re-running updates an existing install in place.
set -euo pipefail

UV_VERSION="0.5.11"
PYTHON_VERSION="3.12"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/backend/.venv"
AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.claimstracker.server com.claimstracker.refresh)

echo "Claims Tracker installer - $ROOT"

# 1. Clear quarantine on anything that arrived via a browser-downloaded zip.
xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null || true

# 2. Refuse to run without the prebuilt frontend (release must include it).
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "ERROR: frontend/dist is missing. Install from a release built with deploy/make_release.sh."
  exit 1
fi

# 3. Ensure uv is installed (pinned version).
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv $UV_VERSION..."
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sh
fi
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null 2>&1 || { echo "ERROR: uv installation failed."; exit 1; }

# 4. Provision a pinned Python and runtime dependencies.
echo "Provisioning Python $PYTHON_VERSION and dependencies..."
uv venv "$VENV" --python "$PYTHON_VERSION"
uv pip install --python "$VENV/bin/python" -r "$ROOT/backend/requirements.txt"

# 5. Download the automation browser.
echo "Downloading the automation browser (Chromium)..."
"$VENV/bin/playwright" install chromium

# 6. Credentials -> Keychain. Read from the terminal even under `curl | bash`.
if (cd "$ROOT/backend" && "$VENV/bin/python" -c "import sys; from app import credentials; sys.exit(0 if credentials.get_credentials() else 1)"); then
  echo "Anthem credentials already in the Keychain - leaving them as-is."
else
  echo "Enter your Anthem credentials (stored only in the macOS Keychain):"
  "$VENV/bin/python" "$ROOT/deploy/store_credentials.py" < /dev/tty
fi
printf "Set up an Anthropic API key for PDF auto-fill? [y/N] "
read -r ans < /dev/tty || ans=""
case "$ans" in
  y|Y) "$VENV/bin/python" "$ROOT/deploy/store_credentials.py" --anthropic < /dev/tty ;;
esac

# 7. Install + load the launchd agents (no npm - dist is prebuilt).
mkdir -p "$ROOT/data/logs" "$AGENTS"
for label in "${LABELS[@]}"; do
  dest="$AGENTS/$label.plist"
  sed "s|@@ROOT@@|$ROOT|g" "$ROOT/deploy/$label.plist.template" > "$dest"
  launchctl unload "$dest" 2>/dev/null || true
  launchctl load "$dest"
  echo "Loaded $label"
done

# 8. Wait for the server to come up, then open the app.
echo -n "Starting server"
for _ in $(seq 1 30); do
  curl -fsS http://localhost:8000/ >/dev/null 2>&1 && break
  echo -n "."; sleep 1
done
echo
open http://localhost:8000 || true

cat <<EOF

Done - Claims Tracker is running at http://localhost:8000
It starts automatically each time you log in.

The first claims refresh opens a Chromium window so you can complete Anthem's MFA once.
To uninstall:  bash "$ROOT/deploy/uninstall.sh"
EOF
