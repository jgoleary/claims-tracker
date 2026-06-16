# Deployment (macOS, local)

One-time setup of claims-tracker as an always-on local service with a daily
Anthem refresh.

## Prerequisites
- Backend venv created and deps installed:
  `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt && playwright install chromium`

## Install
1. Store Anthem credentials in the Keychain (terminal only — never the web UI):
   `backend/.venv/bin/python deploy/store_credentials.py`
2. Build + install the LaunchAgents:
   `bash deploy/install.sh`
3. Open the dashboard at http://localhost:8000

## How it runs
- `com.claimstracker.server` — uvicorn on 127.0.0.1:8000, restarts on crash and at login.
- `com.claimstracker.refresh` — runs `deploy/refresh.sh` once per day (StartInterval 86400).
  A run missed during sleep fires shortly after the laptop wakes.

## MFA
Anthem's Okta session expires periodically. When it does, the scheduled run fails
and you get a macOS notification: "Anthem refresh needs MFA". Open the Refresh
page, run it manually, and complete MFA in the visible browser once. Scheduled runs
then resume silently. **The Mac must be logged in** (locked screen / asleep display
are fine) for a scheduled run to open the browser.

## Logs
- `data/logs/server.log`
- `data/logs/refresh.log`

## Uninstall
`bash deploy/uninstall.sh`
