#!/bin/bash
# Build the frontend and install/load the two LaunchAgents.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.claimstracker.server com.claimstracker.refresh)

echo "Building frontend…"
(cd "$ROOT/frontend" && npm install && npm run build)

mkdir -p "$ROOT/data/logs" "$AGENTS"

for label in "${LABELS[@]}"; do
  dest="$AGENTS/$label.plist"
  sed "s|@@ROOT@@|$ROOT|g" "$ROOT/deploy/$label.plist.template" > "$dest"
  launchctl unload "$dest" 2>/dev/null || true
  launchctl load "$dest"
  echo "Loaded $label"
done

echo
echo "Done. If you haven't stored credentials yet, run:"
echo "  $ROOT/backend/.venv/bin/python $ROOT/deploy/store_credentials.py"
echo "Dashboard: http://localhost:8000"
