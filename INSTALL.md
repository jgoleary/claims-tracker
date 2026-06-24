# Installing Claims Tracker

This guide describes the **current** end-to-end setup for running Claims Tracker as
an always-on local app on macOS. It assumes you are comfortable with the Terminal.

> Claims Tracker runs entirely on your own Mac. Nothing is deployed to the cloud.
> Your Anthem credentials live in the macOS Keychain and never leave the machine.

## What you'll end up with

- A local web app at <http://localhost:8000> that starts automatically at login.
- A background job that refreshes your Anthem claims once a day.

## Prerequisites

Install these first if you don't already have them:

| Tool | Why | Check |
|------|-----|-------|
| **macOS** | Keychain + launchd are macOS-only | — |
| **Python 3.11+** | Runs the backend and automation | `python3 --version` |
| **Node.js + npm** | Builds the frontend | `node -v` / `npm -v` |
| **git** | To download the code | `git --version` |
| **An Anthem account** | The app logs in to pull your claims | — |
| **(optional) Anthropic API key** | Enables PDF auto-fill of new claims | — |

If `python3`, `node`, or `git` are missing, install them (e.g. from
[python.org](https://www.python.org/downloads/),
[nodejs.org](https://nodejs.org/), and the Xcode Command Line Tools via
`xcode-select --install`) before continuing.

## 1. Get the code

```bash
git clone <repository-url> claims-tracker
cd claims-tracker
```

## 2. Set up the backend

Create a virtual environment, install dependencies, and download the browser that
the Anthem automation drives:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium        # one-time, ~150 MB download
cd ..
```

## 3. Store your Anthem credentials in the Keychain

Credentials are entered **only** in the Terminal and written straight to the macOS
Keychain — they never pass through the web app.

```bash
backend/.venv/bin/python deploy/store_credentials.py
```

You'll be prompted for your Anthem email and password. (Re-run this command any time
your password changes.)

**Optional — Anthropic API key** for PDF auto-fill of new submissions:

```bash
backend/.venv/bin/python deploy/store_credentials.py --anthropic
```

Without a key, PDF auto-fill is simply unavailable and you enter claims manually.

## 4. Install the always-on service

This builds the frontend and installs two background agents (the web server and the
daily refresh):

```bash
bash deploy/install.sh
```

The script runs `npm install && npm run build`, then loads:

- `com.claimstracker.server` — the web server on `127.0.0.1:8000`, restarted on crash
  and at every login.
- `com.claimstracker.refresh` — runs once a day to pull fresh claims from Anthem. A
  run missed while the Mac is asleep fires shortly after it wakes.

## 5. Open the app

Visit <http://localhost:8000>.

The first time the daily refresh (or your first manual refresh) runs, a Chromium
window opens so you can complete Anthem's multi-factor authentication. After that the
session is remembered until Anthem expires it.

---

## Multi-factor authentication (MFA)

Anthem's login session expires periodically. When it does, a scheduled refresh fails
and you'll get a macOS notification: **"Anthem refresh needs MFA."** Open the
**Refresh** page in the app, click **Refresh Now**, and complete MFA in the Chromium
window that appears. Scheduled runs then resume on their own.

The Mac must be **logged in** for a scheduled refresh to open the browser (a locked
screen or sleeping display is fine; fully logged out is not).

## Everyday operation

```bash
# Run today's refresh right now, regardless of the schedule
launchctl start com.claimstracker.refresh

# Restart the web server (normally always up)
launchctl kickstart -k gui/$(id -u)/com.claimstracker.server

# Are the agents loaded? Show last run's exit code
launchctl list | grep claimstracker
```

Logs are written to `data/logs/server.log` and `data/logs/refresh.log`.

## Updating to a newer version

```bash
git pull
source backend/.venv/bin/activate
pip install -r backend/requirements-dev.txt   # in case deps changed
bash deploy/install.sh                         # rebuilds frontend, reloads agents
```

## Uninstalling

```bash
bash deploy/uninstall.sh
```

This unloads and removes the two LaunchAgents. Your data in `data/` (the SQLite
database, uploaded PDFs) and your Keychain credentials are left in place; delete them
manually if you want a clean slate.

## Running in development mode (alternative)

If you're working on the code rather than just using the app, you can skip the
always-on service and run the two dev servers directly:

```bash
# Terminal 1 — backend with auto-reload
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload          # http://localhost:8000

# Terminal 2 — frontend with hot reload
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api → :8000
```

## Troubleshooting

- **`playwright install chromium` failed** — re-run it inside the activated venv
  (`source backend/.venv/bin/activate`).
- **`bash deploy/install.sh` fails at the npm step** — confirm `node -v` and `npm -v`
  work, then re-run.
- **Refresh keeps asking for MFA** — make sure the Mac is logged in when the daily job
  runs; complete MFA once from the Refresh page.
- **App won't load at :8000** — check `launchctl list | grep claimstracker` and the
  tail of `data/logs/server.log`.
