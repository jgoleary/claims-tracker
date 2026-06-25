#!/bin/bash
# One-time developer setup: virtualenv + Python deps + the automation browser.
# Safe to re-run. For the always-on app install, use deploy/install.sh instead.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/backend/.venv"

echo "Setting up dev virtualenv at backend/.venv..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install -r "$ROOT/backend/requirements.txt"

echo "Installing the automation browser (Chromium)..."
"$VENV/bin/playwright" install chromium

echo "Enabling the Prettier pre-commit hook..."
git -C "$ROOT" config core.hooksPath .githooks

cat <<EOF

Done. Start the dev servers in two terminals:
  (backend)  cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8001
  (frontend) cd frontend && npm install && npm run dev
EOF
