#!/bin/bash
# One-command bootstrap for Claims Tracker (macOS).
# Usage:  curl -fsSL https://github.com/jgoleary/claims-tracker/releases/latest/download/bootstrap.sh | bash
set -euo pipefail

REPO="jgoleary/claims-tracker"
INSTALL_DIR="${CLAIMS_TRACKER_DIR:-$HOME/claims-tracker}"
TARBALL_URL="https://github.com/$REPO/releases/latest/download/claims-tracker.tar.gz"

echo "Downloading Claims Tracker into $INSTALL_DIR…"
mkdir -p "$INSTALL_DIR"
curl -fsSL "$TARBALL_URL" | tar -xz -C "$INSTALL_DIR" --strip-components=1

cd "$INSTALL_DIR"
# Give the installer a real terminal even though our own stdin is the curl pipe.
exec bash deploy/install.sh < /dev/tty
