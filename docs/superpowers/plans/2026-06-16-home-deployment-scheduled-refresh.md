# Home Deployment + Scheduled Daily Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run claims-tracker as an always-on local macOS service that refreshes Anthem
data once per day, reading credentials from the Keychain and notifying the user when a run
needs MFA.

**Architecture:** Add a Keychain-backed credentials module and use it as a fallback in the
existing `run_automation` worker, which also gains a macOS notification on failure
(classifying MFA-needed vs. generic). FastAPI serves the built frontend so the whole app
is one process. A `deploy/` directory provides `launchd` LaunchAgents (always-on server +
daily refresh) plus setup/install scripts.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy (backend), `keyring` (macOS Keychain),
`launchd`, `osascript`, React/Vite (frontend build).

## Global Constraints

- All money is integer cents — not touched here, but never introduce floats.
- Backend code lives under `backend/app/`; tests under `backend/tests/`; run with `pytest`
  from `backend/`.
- Credentials must never be written to a plaintext file or logged. Keychain only.
- `notify()` and Keychain access are macOS-only and must degrade to a no-op / clear error
  off-platform (don't crash the worker).
- Refresh interval is exactly `86400` seconds (once per day). Server binds
  `127.0.0.1:8000`.
- Follow existing patterns: `keyring` added to `backend/requirements.txt`; helper
  functions are module-level and unit-tested; thread/subprocess orchestration is verified
  manually.

---

### Task 1: Keychain credentials module

**Files:**

- Modify: `backend/requirements.txt`
- Create: `backend/app/credentials.py`
- Test: `backend/tests/test_credentials.py`

**Interfaces:**

- Produces:
  - `credentials.SERVICE: str` = `"claims-tracker-anthem"`
  - `credentials.store_credentials(username: str, password: str) -> None`
  - `credentials.get_credentials() -> tuple[str, str] | None` — returns
    `(username, password)` or `None` if either is missing.

- [ ] **Step 1: Add the dependency**

In `backend/requirements.txt`, add a line after `requests>=2.31.0`:

```
keyring>=24.0.0
```

Then install it:

Run: `cd backend && source .venv/bin/activate && pip install -r requirements.txt`
Expected: `keyring` installs successfully.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_credentials.py`:

```python
import app.credentials as creds


class _FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, key, value):
        self.store[(service, key)] = value

    def get_password(self, service, key):
        return self.store.get((service, key))


def test_store_and_get_roundtrip(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _FakeKeyring())
    creds.store_credentials("me@example.com", "s3cret")
    assert creds.get_credentials() == ("me@example.com", "s3cret")


def test_get_returns_none_when_unset(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _FakeKeyring())
    assert creds.get_credentials() is None


def test_get_returns_none_when_password_missing(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(creds, "keyring", fake)
    fake.set_password(creds.SERVICE, "username", "me@example.com")
    assert creds.get_credentials() is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_credentials.py -v` Expected: FAIL with
`ModuleNotFoundError: No module named 'app.credentials'`

- [ ] **Step 4: Write minimal implementation**

Create `backend/app/credentials.py`:

```python
"""Read/write Anthem credentials in the macOS Keychain via `keyring`."""
import keyring

SERVICE = "claims-tracker-anthem"
_USERNAME_KEY = "username"
_PASSWORD_KEY = "password"


def store_credentials(username: str, password: str) -> None:
    keyring.set_password(SERVICE, _USERNAME_KEY, username)
    keyring.set_password(SERVICE, _PASSWORD_KEY, password)


def get_credentials() -> tuple[str, str] | None:
    username = keyring.get_password(SERVICE, _USERNAME_KEY)
    password = keyring.get_password(SERVICE, _PASSWORD_KEY)
    if not username or not password:
        return None
    return username, password
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_credentials.py -v` Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/credentials.py backend/tests/test_credentials.py
git commit -m "feat: Keychain-backed Anthem credentials module"
```

---

### Task 2: Keychain fallback + failure notification in the automation worker

**Files:**

- Modify: `backend/app/automation.py`
- Test: `backend/tests/test_automation.py` (append)

**Interfaces:**

- Consumes: `credentials.get_credentials()` from Task 1.
- Produces (new module-level helpers in `app.automation`):
  - `_resolve_credentials(username: str, password: str) -> tuple[str, str] | None`
  - `_classify_failure(summary: dict) -> str`
  - `notify(title: str, message: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_automation.py`:

```python
from unittest.mock import patch as _patch

from app import automation as _auto


def test_resolve_credentials_prefers_args():
    assert _auto._resolve_credentials("u", "p") == ("u", "p")


def test_resolve_credentials_falls_back_to_keychain():
    with _patch("app.automation.credentials.get_credentials", return_value=("k", "kp")):
        assert _auto._resolve_credentials("", "") == ("k", "kp")


def test_resolve_credentials_none_when_unset():
    with _patch("app.automation.credentials.get_credentials", return_value=None):
        assert _auto._resolve_credentials("", "") is None


def test_classify_failure_detects_mfa():
    msg = _auto._classify_failure({"stdout": "[auth] ERROR: TimeoutError 120000ms", "stderr": ""})
    assert "MFA" in msg


def test_classify_failure_generic():
    msg = _auto._classify_failure({"stdout": "[claims] ERROR: bad selector", "stderr": ""})
    assert "MFA" not in msg
    assert "failed" in msg.lower()


def test_classify_failure_process_timeout_is_generic():
    msg = _auto._classify_failure({"error": "timed out after 300s"})
    assert "MFA" not in msg


def test_notify_swallows_errors():
    with _patch("app.automation.subprocess.run", side_effect=OSError("no osascript")):
        _auto.notify("t", "m")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_automation.py -v` Expected: FAIL
(`AttributeError: ... has no attribute '_resolve_credentials'`)

- [ ] **Step 3: Implement the helpers and wire them into the worker**

Edit `backend/app/automation.py`. Add the import near the top (after the existing
imports):

```python
from app import credentials
```

Add these module-level helpers (e.g. just below `_write`):

```python
def notify(title: str, message: str) -> None:
    """Best-effort macOS notification; no-op if osascript is unavailable."""
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification {message!r} with title {title!r}'],
            check=False,
            timeout=10,
        )
    except Exception:
        pass


def _resolve_credentials(username: str, password: str) -> tuple[str, str] | None:
    if username and password:
        return username, password
    return credentials.get_credentials()


def _classify_failure(summary: dict) -> str:
    text = (summary.get("stdout", "") + summary.get("stderr", "")).lower()
    if "auth:" in text and "timeout" in text:
        return "Anthem refresh needs MFA — open the Refresh page and run it manually."
    return "Anthem refresh failed — check the Refresh page for details."
```

Replace the body of `_worker` in `run_automation` with credential resolution +
notification:

```python
    def _worker():
        creds = _resolve_credentials(username, password)
        if creds is None:
            with _lock:
                _write({
                    "status": "failed",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "summary": {"error": "no stored credentials"},
                })
            notify(
                "Claims Tracker",
                "No stored Anthem credentials — run deploy/store_credentials.py.",
            )
            return

        env = {**os.environ, "ANTHEM_USERNAME": creds[0], "ANTHEM_PASSWORD": creds[1]}
        try:
            result = subprocess.run(
                [sys.executable, str(_SCRIPT)],
                cwd=str(_SCRIPT.parent.parent),
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
            summary = {
                "returncode": result.returncode,
                "stdout": result.stdout[-2_000:],
                "stderr": result.stderr[-500:],
            }
            status = "complete" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            summary = {"error": "timed out after 300s"}
            status = "failed"
        except Exception as e:
            summary = {"error": str(e)}
            status = "failed"

        with _lock:
            _write({
                "status": status,
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
            })

        if status == "failed":
            notify("Claims Tracker", _classify_failure(summary))
```

Note: the manual UI flow still passes `username`/`password`; the scheduled flow passes
empty strings and falls back to the Keychain.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_automation.py -v` Expected: PASS (all, including the
four pre-existing route tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation.py backend/tests/test_automation.py
git commit -m "feat: Keychain fallback + MFA/failure notification in refresh worker"
```

---

### Task 3: Serve the built frontend from FastAPI

**Files:**

- Create: `backend/app/static_serve.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_static_serve.py`

**Interfaces:**

- Produces: `static_serve.create_spa_router(dist: pathlib.Path) -> fastapi.APIRouter` — a
  catch-all GET router that serves an existing file under `dist`, returns
  `dist/index.html` for unmatched non-API paths, and 404s paths starting with `api`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_static_serve.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.static_serve import create_spa_router


def _app(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')")
    app = FastAPI()
    app.include_router(create_spa_router(tmp_path))
    return TestClient(app)


def test_serves_index_for_unknown_route(tmp_path):
    client = _app(tmp_path)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "<title>app</title>" in resp.text


def test_serves_existing_asset(tmp_path):
    client = _app(tmp_path)
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_api_path_404s(tmp_path):
    client = _app(tmp_path)
    assert client.get("/api/unknown").status_code == 404


def test_root_serves_index(tmp_path):
    client = _app(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<title>app</title>" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_static_serve.py -v` Expected: FAIL with
`ModuleNotFoundError: No module named 'app.static_serve'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/static_serve.py`:

```python
"""Serve the built Vite SPA (frontend/dist) from FastAPI for production."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def create_spa_router(dist: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    return router
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_static_serve.py -v` Expected: PASS (4 tests)

- [ ] **Step 5: Wire it into `main.py`**

In `backend/app/main.py`, add imports at the top:

```python
from pathlib import Path

from app.static_serve import create_spa_router
```

At the **end** of the file (after all `include_router` calls and the `on_startup`
handler), append:

```python
_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.include_router(create_spa_router(_DIST))
```

The catch-all is registered last, so all `/api/...` routes keep precedence; the SPA router
only handles everything else. It is gated on `_DIST.exists()` so `npm run dev` (no build)
and the test suite are unaffected.

- [ ] **Step 6: Verify the full suite still passes**

Run: `cd backend && pytest -q` Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/static_serve.py backend/app/main.py backend/tests/test_static_serve.py
git commit -m "feat: serve built frontend SPA from FastAPI"
```

---

### Task 4: Deploy tooling (LaunchAgents, install/setup scripts)

**Files:**

- Create: `deploy/store_credentials.py`
- Create: `deploy/refresh.sh`
- Create: `deploy/com.claimstracker.server.plist.template`
- Create: `deploy/com.claimstracker.refresh.plist.template`
- Create: `deploy/install.sh`
- Create: `deploy/uninstall.sh`
- Create: `deploy/README.md`

**Interfaces:**

- Consumes: `app.credentials.store_credentials` (Task 1), `POST /api/automation/run`
  (existing), the daily-interval constant `86400`.
- Templates use the literal token `@@ROOT@@`, replaced with the absolute repo path by
  `install.sh`.

- [ ] **Step 1: Credential setup script**

Create `deploy/store_credentials.py`:

```python
"""One-time: store Anthem credentials in the macOS Keychain.

Run with the backend venv:
    backend/.venv/bin/python deploy/store_credentials.py
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import credentials  # noqa: E402

username = input("Anthem email: ").strip()
password = getpass.getpass("Anthem password: ")
if not username or not password:
    print("Both fields are required; nothing stored.")
    sys.exit(1)
credentials.store_credentials(username, password)
print(f"Stored Anthem credentials in the Keychain (service: {credentials.SERVICE}).")
```

- [ ] **Step 2: Refresh wrapper**

Create `deploy/refresh.sh`:

```bash
#!/bin/bash
# Triggers a daily Anthem refresh through the running server.
set -euo pipefail
echo "refresh: starting at $(date)"
curl -fsS -X POST http://localhost:8000/api/automation/run \
  -H 'Content-Type: application/json' -d '{}'
echo
echo "refresh: request accepted at $(date)"
```

- [ ] **Step 3: Server LaunchAgent template**

Create `deploy/com.claimstracker.server.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.claimstracker.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>@@ROOT@@/backend/.venv/bin/uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
  </array>
  <key>WorkingDirectory</key>
  <string>@@ROOT@@/backend</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>@@ROOT@@/data/logs/server.log</string>
  <key>StandardErrorPath</key>
  <string>@@ROOT@@/data/logs/server.log</string>
</dict>
</plist>
```

- [ ] **Step 4: Refresh LaunchAgent template**

Create `deploy/com.claimstracker.refresh.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.claimstracker.refresh</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>@@ROOT@@/deploy/refresh.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>86400</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>@@ROOT@@/data/logs/refresh.log</string>
  <key>StandardErrorPath</key>
  <string>@@ROOT@@/data/logs/refresh.log</string>
</dict>
</plist>
```

- [ ] **Step 5: Install script**

Create `deploy/install.sh`:

```bash
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
```

- [ ] **Step 6: Uninstall script**

Create `deploy/uninstall.sh`:

```bash
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
```

- [ ] **Step 7: Deploy README**

Create `deploy/README.md`:

```markdown
# Deployment (macOS, local)

One-time setup of claims-tracker as an always-on local service with a daily Anthem
refresh.

## Prerequisites

- Backend venv created and deps installed:
  `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt && playwright install chromium`

## Install

1. Store Anthem credentials in the Keychain (terminal only — never the web UI):
   `backend/.venv/bin/python deploy/store_credentials.py`
2. Build + install the LaunchAgents: `bash deploy/install.sh`
3. Open the dashboard at http://localhost:8000

## How it runs

- `com.claimstracker.server` — uvicorn on 127.0.0.1:8000, restarts on crash and at login.
- `com.claimstracker.refresh` — runs `deploy/refresh.sh` once per day (StartInterval
  86400). A run missed during sleep fires shortly after the laptop wakes.

## MFA

Anthem's Okta session expires periodically. When it does, the scheduled run fails and you
get a macOS notification: "Anthem refresh needs MFA". Open the Refresh page, run it
manually, and complete MFA in the visible browser once. Scheduled runs then resume
silently. **The Mac must be logged in** (locked screen / asleep display are fine) for a
scheduled run to open the browser.

## Logs

- `data/logs/server.log`
- `data/logs/refresh.log`

## Uninstall

`bash deploy/uninstall.sh`
```

- [ ] **Step 8: Make scripts executable and verify syntax**

Run:

```bash
chmod +x deploy/refresh.sh deploy/install.sh deploy/uninstall.sh
bash -n deploy/refresh.sh && bash -n deploy/install.sh && bash -n deploy/uninstall.sh
sed 's|@@ROOT@@|/tmp/x|g' deploy/com.claimstracker.server.plist.template | plutil -lint -
sed 's|@@ROOT@@|/tmp/x|g' deploy/com.claimstracker.refresh.plist.template | plutil -lint -
```

Expected: no syntax errors; both plists report `OK`.

- [ ] **Step 9: Commit**

```bash
git add deploy/
git commit -m "feat: macOS deploy tooling — LaunchAgents, install + credential setup"
```

---

## Post-implementation manual verification (on the target Mac)

These require the real machine + Anthem account and are not automated:

1. `bash deploy/install.sh` → dashboard loads at `http://localhost:8000` (frontend served
   by FastAPI).
2. `backend/.venv/bin/python deploy/store_credentials.py` → stores creds; verify with
   `security find-generic-password -s claims-tracker-anthem` (returns an item).
3. `bash deploy/refresh.sh` → a refresh starts; with a valid session it completes and data
   updates; `data/logs/refresh.log` shows the run.
4. Temporarily expire/clear the browser profile to force MFA → confirm the macOS "needs
   MFA" notification fires and the Refresh page shows `failed`.
5. `launchctl list | grep claimstracker` → both agents present.

## Self-Review notes

- **Spec coverage:** §1 always-on service → Task 3 + server plist (Task 4). §2 daily
  refresh Option A → refresh plist `StartInterval 86400` + `RunAtLoad` (Task 4). §3
  Keychain creds → Tasks 1–2 (+ setup script Task 4); location moved to
  `backend/app/credentials.py` for importability/testability, env-var injection preserved
  per spec §3. §4 MFA + notify → Task 2 (`notify`, `_classify_failure`). §5 install
  tooling → Task 4. Out-of-scope items (Tailscale, email, Docker) correctly absent.
- **Placeholders:** none — all code blocks complete.
- **Type consistency:** `get_credentials`/`store_credentials`/`SERVICE` names consistent
  across Tasks 1, 2, 4; `_resolve_credentials`, `_classify_failure`, `notify`,
  `create_spa_router` signatures consistent between definition and use.
