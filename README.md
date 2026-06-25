# Claims Tracker

A local web app to track OON medical claims submitted to Anthem.

## Why this exists

Anthem's manual claim submission process is unreliable. Claims you submit sometimes go
unprocessed entirely, and the ones that do get processed are sometimes processed
incorrectly — for example, OON benefits might get applied when an in-network override
(such as the "Autism clause") should have been, leaving you reimbursed less than you're
owed.

Tracking manually submitted claims as they move through this process is cumbersome. If you
want to identify claims that have stalled or been processed incorrectly, you have to
engage in careful bookkeeping — many Anthem members have reported they keep elaborate
spreadsheets up to date by hand for this purpose.

This app aims to automate as much of that bookkeeping as possible. You record the OON
claims you've submitted along with what you _should_ be reimbursed for each one. The app
then checks Anthem's portal automatically every day and compares the current state of
Anthem's processing against your expectations. When a claim stalls, vanishes from Anthem's
export, gets denied, or is reimbursed for less than expected, it surfaces an alert — so
you know exactly which claims to escalate and why, instead of finding out months later.

## Easy Install (macOS)

Use this if you're not interested in development. You need only macOS and an internet
connection — no developer tools.

Open Terminal and paste:

```bash
curl -fsSL https://github.com/jgoleary/claims-tracker/releases/latest/download/bootstrap.sh | bash
```

The installer downloads everything it needs and asks for your Anthem login (saved only to
the macOS Keychain). You end up with a local web app at <http://localhost:8000> that
starts automatically at login, plus a background job that refreshes your Anthem claims
once a day. The first claims refresh opens a browser window so you can complete Anthem's
multi-factor login once.

To update, re-run the install command above — it updates an existing install in place.

## Uninstall

```bash
bash ~/claims-tracker/deploy/uninstall.sh
```

This stops the background agents. Your data and saved credentials are left untouched; the
script prints how to remove them completely.

---

## Manual setup from source

The one-command installer above is the easiest path. Install from source if you're working
on the code or want to run each step yourself. This assumes you're comfortable with the
Terminal.

### Prerequisites

Install these first if you don't already have them:

| Tool                             | Why                                 | Check                |
| -------------------------------- | ----------------------------------- | -------------------- |
| **macOS**                        | Keychain + launchd are macOS-only   | —                    |
| **Python 3.11+**                 | Runs the backend and automation     | `python3 --version`  |
| **Node.js + npm**                | Builds the frontend                 | `node -v` / `npm -v` |
| **git**                          | To download the code                | `git --version`      |
| **An Anthem account**            | The app logs in to pull your claims | —                    |
| **(optional) Anthropic API key** | Enables PDF auto-fill of new claims | —                    |

If `python3`, `node`, or `git` are missing, install them (e.g. from
[python.org](https://www.python.org/downloads/), [nodejs.org](https://nodejs.org/), and
the Xcode Command Line Tools via `xcode-select --install`) before continuing.

### 1. Get the code

```bash
git clone https://github.com/jgoleary/claims-tracker.git claims-tracker
cd claims-tracker
```

### 2. Run the installer

```bash
bash deploy/install.sh
```

`install.sh` is self-contained: it builds the frontend (release tarballs ship it prebuilt;
from a clone it runs `npm ci && npm run build` for you), provisions a pinned Python and
the backend dependencies (via [`uv`](https://docs.astral.sh/uv/)), downloads the
automation browser (Chromium), prompts for your Anthem login and an optional Anthropic API
key — stored only in the macOS Keychain — and loads the two launchd agents described under
[How it runs](#how-it-runs). When it finishes, the app is running at
<http://localhost:8000>.

The first claims refresh opens a Chromium window so you can complete Anthem's multi-factor
authentication. After that the session is remembered until Anthem expires it.

### Changing credentials later

Credentials live in the Keychain and never pass through the web app. Re-run the script any
time (e.g. after a password change):

```bash
backend/.venv/bin/python deploy/store_credentials.py              # Anthem login
backend/.venv/bin/python deploy/store_credentials.py --anthropic  # Anthropic API key
```

Without an Anthropic key, PDF auto-fill is unavailable and you enter claims manually.

### Updating a from-source install

```bash
git pull
bash deploy/install.sh   # rebuilds the frontend, reinstalls deps, reloads agents
```

## Development

New to the codebase? Start with [ARCHITECTURE.md](ARCHITECTURE.md) for a high-level map of
how the frontend, backend, and automation fit together.

Working on the code rather than just using the app? Skip the always-on service and run the
two dev servers directly. First set up the dev virtualenv and automation browser
(one-time, ~150 MB Chromium download; safe to re-run):

```bash
bash deploy/dev_setup.sh
```

Then start the servers. The dev backend runs on **:8001** to avoid colliding with the
always-on launch agent on :8000 (which `KeepAlive` would just respawn if you stopped it):

```bash
# Terminal 1 — backend with auto-reload
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8001   # http://localhost:8001

# Terminal 2 — frontend with hot reload
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api → :8001
```

## Tips

### How it runs

`deploy/install.sh` — run by both the easy installer and the from-source setup — loads two
launchd agents:

- `com.claimstracker.server` — the web server on `127.0.0.1:8000`, restarted on crash and
  at every login.
- `com.claimstracker.refresh` — runs once a day to pull fresh claims from Anthem. A run
  missed while the Mac is asleep fires shortly after it wakes.

### Multi-factor authentication (MFA)

Anthem's login session expires periodically. When it does, a scheduled refresh fails and
you'll get a macOS notification: **"Anthem refresh needs MFA."** Open the **Refresh** page
in the app, click **Refresh Now**, and complete MFA in the Chromium window that appears.
Scheduled runs then resume on their own.

The Mac must be **logged in** for a scheduled refresh to open the browser (a locked screen
or sleeping display is fine; fully logged out is not).

### Everyday operation

```bash
# Run today's refresh right now, regardless of the schedule
launchctl start com.claimstracker.refresh

# Restart the web server (normally always up)
launchctl kickstart -k gui/$(id -u)/com.claimstracker.server

# Are the agents loaded? Show last run's exit code
launchctl list | grep claimstracker
```

Logs are written to `data/logs/server.log` and `data/logs/refresh.log`.

### Troubleshooting

- **`playwright install chromium` failed** — re-run it directly:
  `backend/.venv/bin/playwright install chromium`.
- **`bash deploy/install.sh` fails at the npm step** — confirm `node -v` and `npm -v`
  work, then re-run.
- **Refresh keeps asking for MFA** — make sure the Mac is logged in when the daily job
  runs; complete MFA once from the Refresh page.
- **App won't load at :8000** — check `launchctl list | grep claimstracker` and the tail
  of `data/logs/server.log`.
