#!/bin/bash
# Remove Claims Tracker's background agents.
# Run via:  bash deploy/uninstall.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"

for label in com.claimstracker.server com.claimstracker.refresh; do
  dest="$AGENTS/$label.plist"
  launchctl unload "$dest" 2>/dev/null || true
  rm -f "$dest"
  echo "Removed $label"
done

cat <<EOF

Background agents removed - the app no longer starts at login.

Left in place (delete manually for a clean slate):
  - Your data:        $ROOT/data        (SQLite database, uploaded PDFs)
  - The app + venv:   $ROOT
  - Keychain entries: services 'claims-tracker-anthem' and 'claims-tracker-anthropic'
                      (remove via Keychain Access if you want them gone)
EOF
