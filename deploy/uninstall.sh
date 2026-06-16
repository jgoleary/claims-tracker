#!/bin/bash
# Unload and remove the two LaunchAgents.
set -euo pipefail
AGENTS="$HOME/Library/LaunchAgents"
for label in com.claimstracker.server com.claimstracker.refresh; do
  dest="$AGENTS/$label.plist"
  launchctl unload "$dest" 2>/dev/null || true
  rm -f "$dest"
  echo "Removed $label"
done
