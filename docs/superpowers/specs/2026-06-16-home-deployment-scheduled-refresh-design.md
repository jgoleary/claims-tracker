# Home Deployment + Scheduled Auto-Refresh — Design

**Date:** 2026-06-16
**Status:** Approved (pending spec review)

## Goal

Run claims-tracker as an always-on service on the user's macOS laptop, and refresh
Anthem data automatically **once per day** without manual interaction in the common
case. Credentials and data stay on the local machine.

## Constraints & key facts

- **Anthem login is MFA-gated and headful.** Okta SSO requires a human to complete
  MFA in a *visible* browser. Session cookies persist in `data/browser-profile/`, so
  MFA is only needed when the Okta session expires (days–weeks). MFA **cannot** be
  fully eliminated for unattended runs; the system must degrade gracefully when a run
  needs MFA.
- **Host is a laptop that is frequently closed/asleep.** A fixed wall-clock schedule
  cannot be relied on. We use **Option A**: schedule daily, and lean on `launchd`'s
  behavior of running a missed `StartInterval` job shortly after wake. No `pmset`
  scheduled wake.
- **Headful browser requires a GUI login session.** A `launchd` *LaunchAgent* runs in
  the user's Aqua session, so it can open the browser whenever the user is **logged in**.
  Locked screen / asleep display are fine; being logged out is not.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Hosting | Always-on home machine (this macOS laptop) |
| Scheduling | Option A — daily `StartInterval`, catch-up on wake |
| Refresh frequency | Once per day (`StartInterval = 86400s`) |
| Credentials | macOS Keychain via the `keyring` library |
| Notifications | Native macOS notification (`osascript`) on failure / MFA-needed |
| Remote access | Local only (no Tailscale/tunnel for now) |

## Architecture

### 1. Always-on local service (one process)

Replace the two-terminal dev setup (`uvicorn --reload` + `vite`) with a single
production process:

- `npm run build` → `frontend/dist`.
- `main.py` serves `frontend/dist` via `StaticFiles` mounted at `/`, with the API still
  under `/api`, plus a catch-all route returning `index.html` for client-side (SPA)
  routes. API routes take precedence over the static catch-all.
- LaunchAgent `com.claimstracker.server`: runs `uvicorn app.main:app` (no `--reload`) at
  login with `KeepAlive=true`. Dashboard always at `http://localhost:8000`.
- Logs → `data/logs/server.log` (stdout/stderr).

In dev, the existing Vite proxy flow is unchanged; static-serving only activates when
`frontend/dist` exists (or is gated behind an env flag), so `npm run dev` keeps working.

### 2. Scheduled refresh (Option A)

- LaunchAgent `com.claimstracker.refresh`: `StartInterval = 86400`. Missed intervals
  (laptop asleep) run once shortly after wake.
- Runs `deploy/refresh.sh`, which does
  `curl -fsS -X POST http://localhost:8000/api/automation/run` with an empty body.
- Going through the existing API reuses `run_automation()`, `data/state.json`, the
  Refresh-page status, the matching pass, and notifications — a single code path shared
  by manual and scheduled runs.
- Logs → `data/logs/refresh.log`.

### 3. Credentials in macOS Keychain

- New `automation/credentials.py` using `keyring`:
  - `get_credentials() -> (username, password) | None` reads two items under service
    `claims-tracker-anthem` (one for username, one for password).
  - `store_credentials(username, password)` writes them.
- One-time setup script `deploy/store_credentials.py`: prompts in the terminal and calls
  `store_credentials()`. Credentials never traverse the web layer during setup.
- `automation.py:run_automation()`: if `username`/`password` are empty, load them from
  `credentials.py` and inject as `ANTHEM_USERNAME` / `ANTHEM_PASSWORD` env vars for the
  subprocess. If Keychain has none, the run fails fast with a clear "no stored
  credentials" message + notification.
- The manual Refresh-page flow (user types creds) is unchanged; scheduled runs rely on
  the Keychain fallback. `keyring` added to `backend/requirements.txt`.

### 4. MFA handling + notifications

- Scheduled runs use the existing **headful** persistent-context browser.
- Common case: valid session cookie → run completes silently, no UI interaction.
- Expired session: `login()` reaches its MFA wait and times out (~120s) → run marked
  `failed`.
- New `notify(title, message)` helper (`osascript -e 'display notification ...'`),
  invoked from the `run_automation` worker on failure. The message distinguishes
  **MFA-needed** ("Anthem refresh needs MFA — open the Refresh page") from other errors,
  classified by inspecting the failure (timeout on the MFA wait vs. other exceptions).
- Recovery: user opens the Refresh page, runs manually, completes MFA in the visible
  browser once; scheduled runs resume silently until the next expiry.

### 5. Install tooling — `deploy/`

- `com.claimstracker.server.plist` and `com.claimstracker.refresh.plist` — LaunchAgent
  templates with absolute paths rendered at install time.
- `refresh.sh` — the curl wrapper.
- `store_credentials.py` — one-time Keychain setup.
- `install.sh` — builds the frontend, renders + copies plists to
  `~/Library/LaunchAgents`, `launchctl load`s them, creates `data/logs/`.
- `uninstall.sh` — `launchctl unload`s and removes the plists.

## Components & boundaries

| Unit | Purpose | Depends on |
|---|---|---|
| `automation/credentials.py` | Read/write Anthem creds in Keychain | `keyring` |
| `automation.py` (edit) | Keychain fallback + failure notification | `credentials.py`, `notify` |
| `notify` helper | macOS notification | `osascript` |
| `main.py` (edit) | Serve built SPA + API | `StaticFiles` |
| `deploy/*` | Install/schedule/store-creds tooling | `launchd`, `curl`, `keyring` |

## Error handling

- No stored credentials → fail fast, notify "no stored credentials; run setup".
- MFA timeout → fail, notify "needs MFA".
- Server down when refresh fires → `refresh.sh` curl fails (non-zero), logged to
  `refresh.log`; `KeepAlive` should keep the server up, so this is rare.
- Anthem transient site error → existing `check_for_site_error` raises; surfaced as a
  generic failure notification.

## Testing

- Unit-test `credentials.py` against a fake `keyring` backend (set/get round-trip,
  missing-creds case).
- Unit-test the `run_automation` Keychain-fallback branch (creds loaded into env when
  none passed; fast-fail when none stored) with `keyring`/subprocess mocked.
- Unit-test the failure classifier (MFA-needed vs. generic) and that `notify` is invoked
  on failure.
- Static-serving: a smoke test that an unknown non-`/api` path returns `index.html` and
  `/api/...` still routes to the API.
- `install.sh` / plist rendering verified manually on the target machine.

## Out of scope (YAGNI)

Remote access / Tailscale, email notifications, Docker, cloud hosting, programmatic OTP /
MFA bypass, multi-user auth.

## Unchanged

All existing app logic: matching, alerts, ingest, Refresh-page UI, manual run flow. This
work is additive: a static-serving change in `main.py`, a Keychain fallback + notify in
`automation.py`, a new `credentials.py`, and the `deploy/` tooling.
