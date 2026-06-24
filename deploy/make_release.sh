#!/bin/bash
# Maintainer-only: build the frontend, package a release tarball, publish to GitHub.
# Usage:  bash deploy/make_release.sh vX.Y.Z [--dry-run]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:?usage: make_release.sh vX.Y.Z [--dry-run]}"
DRY=0; [ "${2:-}" = "--dry-run" ] && DRY=1

cd "$ROOT"
echo "Building frontend…"
npm --prefix frontend ci
npm --prefix frontend run build
[ -f frontend/dist/index.html ] || { echo "ERROR: frontend/dist not built."; exit 1; }

STAGE_PARENT="$(mktemp -d)"
STAGE="$STAGE_PARENT/claims-tracker"
mkdir -p "$STAGE"
rsync -a \
  --exclude '.git' --exclude 'data' --exclude 'backend/.venv' \
  --exclude 'frontend/node_modules' --exclude 'dist-release' \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$ROOT/" "$STAGE/"

OUT="$ROOT/dist-release"
mkdir -p "$OUT"
TARBALL="$OUT/claims-tracker.tar.gz"
tar -czf "$TARBALL" -C "$STAGE_PARENT" claims-tracker
echo "Tarball: $TARBALL"

# Sanity: the prebuilt frontend must be inside the tarball, data must not.
tar -tzf "$TARBALL" | grep -q 'claims-tracker/frontend/dist/index.html' \
  || { echo "ERROR: frontend/dist missing from tarball."; exit 1; }
if tar -tzf "$TARBALL" | grep -q 'claims-tracker/data/'; then
  echo "ERROR: data/ leaked into tarball."; exit 1
fi

if [ "$DRY" = "1" ]; then
  echo "dry-run: built and validated tarball; skipping GitHub release."
  exit 0
fi

echo "Publishing release $TAG…"
gh release create "$TAG" "$TARBALL" "$ROOT/deploy/bootstrap.sh" \
  --title "$TAG" --notes "Claims Tracker $TAG" \
|| gh release upload "$TAG" "$TARBALL" "$ROOT/deploy/bootstrap.sh" --clobber
echo "Done."
