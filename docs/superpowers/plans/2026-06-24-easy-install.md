# Easy Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Mac + Anthem user install (and uninstall) Claims Tracker with one pasted
Terminal command, no developer tools.

**Architecture:** A maintainer script (`make_release.sh`) publishes a GitHub Release
containing a tarball with a **prebuilt `frontend/dist`** plus a standalone `bootstrap.sh`.
End users run `curl … | bash` (or download + `bash deploy/install.sh`). The installer uses
**uv** to provision a pinned Python, installs runtime deps + Chromium, writes Anthem creds
to the Keychain, and loads the existing launchd agents — skipping npm because `dist` is
prebuilt. Invoking through `bash` (never Finder double-click) sidesteps Gatekeeper.

**Tech Stack:** Bash, uv (Astral), Playwright/Chromium, launchd, GitHub Releases via `gh`,
existing FastAPI backend + `app.credentials` Keychain module.

## Global Constraints

- **Platform:** macOS only.
- **Invocation:** all installer/uninstaller scripts run via `bash <script>` or
  `curl … | bash` — **never** double-clicked in Finder, never `./script`. (This is what
  keeps Gatekeeper from firing.)
- **Credentials never touch the web layer** — they go straight to the macOS Keychain via
  `deploy/store_credentials.py` / `app.credentials`. Prompts must read from `/dev/tty` so
  they work under `curl | bash`.
- **Repo:** `jgoleary/claims-tracker`. **Stable release asset names:**
  `claims-tracker.tar.gz` and `bootstrap.sh` (so `releases/latest/download/<name>`
  resolves).
- **Runtime deps:** `backend/requirements.txt` only (NOT `-dev`). **uv version pinned** to
  `0.5.11`. **Python pinned** to `3.12`.
- **No shellcheck installed** — verify scripts with `bash -n <script>` (syntax) plus a
  real run.
- Tarball top-level dir is `claims-tracker/`; `bootstrap.sh` extracts with
  `--strip-components=1`.

---

### Task 1: Rewrite `deploy/install.sh` as the self-contained installer

**Files:**

- Modify (full rewrite): `deploy/install.sh`

**Interfaces:**

- Consumes: `backend/requirements.txt`; `deploy/store_credentials.py`;
  `app.credentials.get_credentials()` (returns `(user, pass)` or `None`); plist templates
  `deploy/com.claimstracker.{server,refresh}.plist.template` (contain `@@ROOT@@`);
  `frontend/dist/index.html` (must exist, produced by Task 3).
- Produces: a working `backend/.venv`, two loaded launchd agents, server reachable at
  `http://localhost:8000`. Called by `deploy/bootstrap.sh` (Task 2) as
  `bash deploy/install.sh </dev/tty`.

- [ ] **Step 1: Write the new `deploy/install.sh`**

```bash
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

echo "Claims Tracker installer — $ROOT"

# 1. Clear quarantine on anything that arrived via a browser-downloaded zip.
xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null || true

# 2. Refuse to run without the prebuilt frontend (release must include it).
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "ERROR: frontend/dist is missing. Install from a release built with deploy/make_release.sh."
  exit 1
fi

# 3. Ensure uv is installed (pinned version).
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv $UV_VERSION…"
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sh
fi
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null 2>&1 || { echo "ERROR: uv installation failed."; exit 1; }

# 4. Provision a pinned Python and runtime dependencies.
echo "Provisioning Python $PYTHON_VERSION and dependencies…"
uv venv "$VENV" --python "$PYTHON_VERSION"
uv pip install --python "$VENV/bin/python" -r "$ROOT/backend/requirements.txt"

# 5. Download the automation browser.
echo "Downloading the automation browser (Chromium)…"
"$VENV/bin/playwright" install chromium

# 6. Credentials → Keychain. Read from the terminal even under `curl | bash`.
if (cd "$ROOT/backend" && "$VENV/bin/python" -c "import sys; from app import credentials; sys.exit(0 if credentials.get_credentials() else 1)"); then
  echo "Anthem credentials already in the Keychain — leaving them as-is."
else
  echo "Enter your Anthem credentials (stored only in the macOS Keychain):"
  "$VENV/bin/python" "$ROOT/deploy/store_credentials.py" < /dev/tty
fi
printf "Set up an Anthropic API key for PDF auto-fill? [y/N] "
read -r ans < /dev/tty || ans=""
case "$ans" in
  y|Y) "$VENV/bin/python" "$ROOT/deploy/store_credentials.py" --anthropic < /dev/tty ;;
esac

# 7. Install + load the launchd agents (no npm — dist is prebuilt).
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

Done — Claims Tracker is running at http://localhost:8000
It starts automatically each time you log in.

The first claims refresh opens a Chromium window so you can complete Anthem's MFA once.
To uninstall:  bash "$ROOT/deploy/uninstall.sh"
EOF
```

- [ ] **Step 2: Syntax-check the script**

Run: `bash -n deploy/install.sh` Expected: no output, exit 0.

- [ ] **Step 3: Real run on this machine (acceptance)**

Run: `bash deploy/install.sh` (requires `frontend/dist`; if absent, build it first with
`npm --prefix frontend run build`). Expected: uv installs, venv is created, Chromium
downloads, you are prompted for Anthem creds (or told they already exist), both agents
print "Loaded …", and the browser opens to a working app at `http://localhost:8000`.

- [ ] **Step 4: Verify the venv can run the server binary**

Run: `backend/.venv/bin/uvicorn --version` Expected: prints a uvicorn version (confirms
runtime deps installed into the venv).

- [ ] **Step 5: Verify re-run is idempotent and skips the cred prompt**

Run: `bash deploy/install.sh` Expected: prints "Anthem credentials already in the Keychain
— leaving them as-is." and finishes without error.

- [ ] **Step 6: Commit**

```bash
git add deploy/install.sh
git commit -m "feat(install): self-contained uv-based installer, no npm/system Python"
```

---

### Task 2: Create `deploy/bootstrap.sh` (the `curl | bash` entry point)

**Files:**

- Create: `deploy/bootstrap.sh`

**Interfaces:**

- Consumes: GitHub Release asset `claims-tracker.tar.gz` (top dir `claims-tracker/`,
  produced by Task 3); runs `deploy/install.sh` (Task 1).
- Produces: an unpacked install at `${CLAIMS_TRACKER_DIR:-$HOME/claims-tracker}`, then
  hands off to the installer with a real TTY.

- [ ] **Step 1: Write `deploy/bootstrap.sh`**

```bash
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
```

- [ ] **Step 2: Syntax-check**

Run: `bash -n deploy/bootstrap.sh` Expected: no output, exit 0.

- [ ] **Step 3: Verify the URL shape matches the published asset name**

Run: `grep -n 'claims-tracker.tar.gz' deploy/bootstrap.sh` Expected: the `TARBALL_URL`
line references `releases/latest/download/claims-tracker.tar.gz` — the exact stable asset
name produced in Task 3.

- [ ] **Step 4: Commit**

```bash
git add deploy/bootstrap.sh
git commit -m "feat(install): add curl|bash bootstrap entry point"
```

---

### Task 3: Create `deploy/make_release.sh` (maintainer packaging)

**Files:**

- Create: `deploy/make_release.sh`
- Modify: `.gitignore` (ignore the local build output dir)

**Interfaces:**

- Consumes: `npm --prefix frontend run build` → `frontend/dist`; `deploy/bootstrap.sh`
  (Task 2).
- Produces: `dist-release/claims-tracker.tar.gz` (top dir `claims-tracker/`, includes
  `frontend/dist`, excludes `data/`, `.venv`, `node_modules`, `.git`); publishes it +
  `bootstrap.sh` as Release assets. This tarball is what Task 2 downloads.

- [ ] **Step 1: Add the build output dir to `.gitignore`**

Append this line to `.gitignore`:

```
dist-release/
```

- [ ] **Step 2: Write `deploy/make_release.sh`**

```bash
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
```

- [ ] **Step 3: Syntax-check**

Run: `bash -n deploy/make_release.sh` Expected: no output, exit 0.

- [ ] **Step 4: Dry-run build and validate the tarball (acceptance)**

Run: `bash deploy/make_release.sh v0.0.0-test --dry-run` Expected: frontend builds, prints
"Tarball: …/dist-release/claims-tracker.tar.gz", and exits 0 (the embedded `grep`
assertions confirm `frontend/dist/index.html` is present and `data/` is absent).

- [ ] **Step 5: Commit**

```bash
git add deploy/make_release.sh .gitignore
git commit -m "feat(release): add make_release.sh packaging script"
```

---

### Task 4: Update `deploy/uninstall.sh` to keep data and explain a clean slate

**Files:**

- Modify (full rewrite): `deploy/uninstall.sh`

**Interfaces:**

- Consumes: nothing new.
- Produces: removes both launchd agents; documents what is intentionally kept.

- [ ] **Step 1: Rewrite `deploy/uninstall.sh`**

```bash
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

Background agents removed — the app no longer starts at login.

Left in place (delete manually for a clean slate):
  - Your data:        $ROOT/data        (SQLite database, uploaded PDFs)
  - The app + venv:   $ROOT
  - Keychain entries: services 'claims-tracker-anthem' and 'claims-tracker-anthropic'
                      (remove via Keychain Access if you want them gone)
EOF
```

- [ ] **Step 2: Syntax-check**

Run: `bash -n deploy/uninstall.sh` Expected: no output, exit 0.

- [ ] **Step 3: Run it (acceptance)**

Run: `bash deploy/uninstall.sh` Expected: prints "Removed com.claimstracker.server" /
"Removed com.claimstracker.refresh" (or no-ops cleanly if not loaded) and the "Left in
place" summary. `data/` still exists afterward.

- [ ] **Step 4: Re-install to restore the running service**

Run: `bash deploy/install.sh` Expected: agents reloaded, app reachable again (returns the
machine to a working state after the uninstall test).

- [ ] **Step 5: Commit**

```bash
git add deploy/uninstall.sh
git commit -m "feat(install): uninstall keeps data and explains full removal"
```

---

### Task 5: Put Install / Uninstall at the top of `README.md`

**Files:**

- Modify: `README.md`

**Interfaces:**

- Consumes: `INSTALL.md` (existing manual guide); the commands from Tasks 1–4.
- Produces: user-facing entry point. No code depends on this.

- [ ] **Step 1: Insert the user-facing sections after the title/description and before
      `## Development`**

Replace the region from the `Local web app…` description line through (but not including)
`## Development` with:

````markdown
Local web app to track OON medical claims submitted to Anthem.

## Install (macOS)

You need only macOS and an internet connection — no developer tools.

**Option 1 — one command (recommended).** Open Terminal and paste:

```bash
curl -fsSL https://github.com/jgoleary/claims-tracker/releases/latest/download/bootstrap.sh | bash
```
````

**Option 2 — download first.** Download `claims-tracker.tar.gz` from the
[latest release](https://github.com/jgoleary/claims-tracker/releases/latest), double-click
to unpack, then in Terminal type `bash ` (with a trailing space), **drag the unpacked
`deploy/install.sh` into the Terminal window** to fill in its path, and press Return.

Either way the installer downloads everything it needs, asks for your Anthem login (saved
only to the macOS Keychain), and opens the app at <http://localhost:8000>. The first
claims refresh opens a browser window so you can complete Anthem's multi-factor login
once.

> Don't double-click `install.sh` in Finder — run it through `bash` as shown so macOS
> doesn't block it.

## Uninstall

```bash
bash ~/claims-tracker/deploy/uninstall.sh
```

This stops the background agents. Your data and saved credentials are left untouched; the
script prints how to remove them completely.

## Updating

Re-run the install command above — it updates an existing install in place.

## Development

````

- [ ] **Step 2: Add a pointer to the manual guide under Development**

Immediately after the `## Development` heading line, add:

```markdown

> Running the app as a user? See **Install (macOS)** above. The steps below are for
> working on the code; the full manual/from-source setup lives in [INSTALL.md](INSTALL.md).
````

- [ ] **Step 3: Verify structure and links**

Run: `grep -nE '^## (Install|Uninstall|Updating|Development)' README.md` Expected: the
four headings appear in that order, with Install/Uninstall/Updating above Development.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: lead README with one-command install and uninstall"
```

---

## Notes for the implementer

- **Order matters:** Task 1 (install.sh) needs `frontend/dist` to run end-to-end; build it
  with `npm --prefix frontend run build` (or run Task 3's dry-run first) before Task 1
  Step 3.
- **This replaces the old behavior** where `deploy/install.sh` ran `npm run build`.
  Developers now build via `npm --prefix frontend run build` / `npm run dev` directly; the
  installer no longer touches npm.
- **`get_credentials()`** is documented in CLAUDE.md as returning `(username, password)`
  or `None`; the install.sh check in Task 1 Step 1 relies on exactly that. If its name
  differs, fix the one-liner in Step 1 and re-run Step 5.
