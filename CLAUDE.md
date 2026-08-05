# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## Commands

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # single file: runtime + test deps
playwright install chromium   # one-time, needed for automation

pytest                              # all tests
pytest tests/test_matching.py       # single file
pytest tests/test_ingest.py -k csv  # single test by keyword

uvicorn app.main:app --reload       # dev server on :8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev     # dev server on :5173 (proxies /api → :8000)
npm run build   # type-check + bundle
npm run lint
```

## Architecture

### Data flow

1. User submits OON claims via the frontend form → stored in `submissions` table.
2. Playwright automation (`automation/fetch_all.py`) or manual CSV upload ingests Anthem's
   export → upserted into `anthem_claims` table.
3. Matching algorithm links submissions ↔ anthem_claims via the `matches` table. Matching
   runs automatically after every CSV ingest, submission create, and submission update.
4. Alert flags are computed on-read (not stored) from the match state.
5. Each CSV ingest then reopens any manually resolved submission that picked up a new flag
   (see Manual resolution).

### Backend (`backend/app/`)

- **FastAPI** app in `main.py`; all routes mounted under `/api`.
- **SQLite** via SQLAlchemy 2.x; `database.py` holds the engine and `get_db()` dependency;
  schema auto-creates on startup via `init_db()`.
- **All money is integer cents** — never floats. `ingest.py:_parse_money()` converts
  `"$1,190.00"` → `119000`.
- **`models.py`** — six tables: `submissions`, `anthem_claims`, `matches`,
  `provider_aliases`, `plan_config`, `benefits_snapshots`.
- **`matching.py`** — `run_matching()` is called after every CSV ingest, submission
  create, and submission update. Three-tier logic: (1) exact/prefix/alias provider match →
  auto; (2) member+date match but no provider → suggestion; (3) ambiguous multi-match →
  suggestion.
- **`alerts.py`** — `compute_flags(submission, match, latest_ingest_at=None)` returns a
  list of `Alert` dataclasses. Thresholds live in `config.py` (MISSING_DAYS=30,
  STALE_PENDING_DAYS=30, UNDERPAID_MIN_CENTS=$25, UNDERPAID_PCT=10%). `APPROVED_ZERO_PAID`
  flag is suppressed when `expected_reimbursement == 0`. The `VANISHED` flag (red) fires
  when a matched claim's `last_seen_at` predates `latest_ingest_at` (= `max(last_seen_at)`
  across all anthem_claims, supplied by `routes/submissions.latest_ingest_at(db)`) — i.e.
  the claim dropped out of Anthem's latest export. Ingest is upsert-only and never deletes
  vanished claims, so this is how a disappeared-but-still-matched claim gets surfaced.
  `compute_flags()` is a thin wrapper that suppresses everything for a resolved or
  superseded submission and otherwise delegates to `compute_raw_flags()`, which does the
  actual work; call the raw variant only when you need to see through a resolution.
- **`resolution.py`** — `reopen_resolved(db)` undoes manual resolutions that no longer
  hold. See Manual resolution.
- **`ingest.py`** — `ingest_claims_csv()` parses the Anthem CSV (BOM-safe via `utf-8-sig`,
  handles `"Not Available"` dates, `"$1,190.00"` money), upserts anthem_claims, then calls
  `run_matching()` followed by `resolution.reopen_resolved()`. `_parse_date()` accepts
  both ISO (`2026-05-26`) and Anthem's display format (`May 26, 2026`) — the
  `/member/claims` export uses the display format. `ingest_benefits()` inserts a
  `BenefitsSnapshot` row per network. Anthem's export uses `Claim Number`, `Claim Type`,
  `Provided By`, and `Claim Received` — the parser accepts both those names and legacy
  alternatives. `_parse_patient_name()` canonicalizes the `Patient` field
  (`"Nolan O'leary (2019-02-14)"`) to the **first name only** (`"Nolan"`) — Anthem exports
  the name inconsistently (`"First Last"` vs `"First"`) across exports, so the surname/DOB
  are dropped to keep one person from fragmenting into multiple `patient_name` values.
  Matching compares on first name (`matching.py:_first_name`) so full-name submissions
  still link to first-name claims.
- **`storage.py`** — `Storage` ABC with `LocalFileStorage` impl. PDF files stored under
  `data/pdfs/`. The `pdf_path` column is a storage key, not a raw filesystem path. Swap to
  S3 by implementing `Storage` and calling `set_storage()`.
- **`automation.py`** — runs the Playwright scripts as subprocesses (using
  `sys.executable` so they share the backend venv) in background threads. Three jobs, each
  with its own state file: `run_automation()` → `fetch_all.py` / `data/state.json`,
  `run_escalation()` → `ih_escalate.py` / `data/escalation_state.json`, and
  `run_claim_filing()` → `submit_claim.py` / `data/claim_filing_state.json`.
  `run_automation` accepts `username`/`password` and passes them as env vars to the
  subprocess — credentials are never written to disk. All three share `_run_subprocess()`
  (which normalizes the outcome to `(status, summary)`) and one `_any_running()`
  single-flight guard: the jobs run headfully out of the same browser profile, so only one
  may run at a time. `_materialize_pdf()` writes a submission's stored PDF to a temp dir
  under its **original basename** (so an uploaded file isn't named `tmp8f3a91.pdf`);
  `_cleanup_pdf()` removes it afterwards.
- **`config.py`** — `plan_year_dates(year: int) -> (date, date)` returns Jan 1 / Dec 31
  for any calendar year. All list/totals endpoints accept a `year` query param (defaults
  to current year).
- **`extraction.py`** — sends an uploaded claim PDF to Claude (`claude-sonnet-4-6`) to
  prefill member/provider/first-service-date/billed. The Anthropic API key resolves
  **Keychain → `ANTHROPIC_API_KEY` env var** and is set via
  `deploy/store_credentials.py --anthropic`. Returns `configured=False` when no key is set
  so the UI falls back to manual entry. Expected reimbursement is computed client-side,
  not extracted.

### Plan year filtering

Every data endpoint (`/submissions`, `/anthem-claims`, `/dashboard`, `/totals`) accepts
`?year=YYYY` and filters by `service_date`. The frontend stores the selected year in
`YearContext` and passes it to all queries. The sidebar dropdown sets it globally.

### Totals logic

- CSV rollup sums `deductible + coinsurance` from `anthem_claims` for the selected plan
  year.
- **In-network spending counts toward both the in-network and OON accumulators** —
  in-network claims are added to both buckets in `_get_csv_rollup`.
- The Totals page shows spent, remaining (= limit − spent), and diff vs. CSV sum for each
  network.

### Provider alias learning

When the user confirms a match suggestion (`match_type="confirmed"`), `routes/matches.py`
automatically writes a `ProviderAlias` row mapping `normalize(submission.provider_name)` →
`normalize(claim.provider_name)`. Future matching uses these aliases for auto-matching.

### Submission filing status

`submitted_date` is nullable and is set when the user confirms the claim was uploaded to
Anthem (two-step Add Submission modal). The `UNSUBMITTED` info flag surfaces claims that
have no `submitted_date`.

Creating a submission now drives Anthem's claim wizard automatically (see Anthem claim
filing), but only as far as the upload step — the automation never concludes that a claim
was filed, so `submitted_date` is still set only by the user's own confirmation.

### Anthem claim filing

`automation/submit_claim.py` drives Anthem's out-of-network medical claim wizard: Medical
→ "Doctor or other medical specialist" → patient → requirements → upload the PDF → wait
out Anthem's file processing. It then **stops at "Step 3 of 5"** and holds the browser
open (15 min) for the user to complete the remaining steps and click Submit. Nothing is
ever filed without a human.

- Triggered from the Add Submission modal's step-2 screen (which is the **only** warning
  that the user must finish in the browser — there is deliberately no notification or
  injected page banner), and from the "File with Anthem" row action on the Submissions
  table, shown when a submission has a PDF and no `submitted_date`. That row action is
  also the retry path after a failed or refused run.
- A PDF is mandatory: the Add Submission button is disabled without one, and
  `POST /api/submissions/{id}/file-with-anthem/run` 400s if `pdf_path` is unset.
- Patient selection compares the submission's `member_name` against the dropdown's
  `FIRST M LAST (MM/DD/YYYY)` options via `_normalize_name` / `match_patient_options`
  (surnames compared only when both sides have one). Zero or 2+ matches raises
  `AmbiguousPatientError` — the script refuses to guess, fails the run, and leaves the
  browser open on the dropdown.
- `CLAIM_DRY_RUN=1` stops before "Submit a Claim", the last point before Anthem creates
  any server-side state — use it to exercise login, steps 1-3 and the patient matcher
  against the real site with no side effects.
- Every wizard step is gated on its page heading (`_wait_for_page`) before acting: four
  pages carry a "Next" button, so acting before the SPA navigates silently skips a step.

### Manual resolution

`resolved_at` marks a submission the user has closed out by hand — flags that are accurate
but not actionable, e.g. an `OVERPAID` claim that would otherwise sit in the list forever.
`compute_flags()` returns `[]` for a resolved submission (same early return as
`superseded_by_id`), so it drops off the Dashboard and out of the "Hide resolved
submissions" view. Set/cleared via `POST`/`DELETE /api/submissions/{id}/resolve`; the
Resolve button and the Undo banner live on SubmissionDetail.

A resolution is not permanent. `resolution.py:reopen_resolved()` runs after every claims
ingest and clears `resolved_at` on any resolved submission whose current flags include a
type that wasn't in `resolved_flags` — the comma-separated snapshot taken at resolve time.
So an overpaid-and-resolved claim stays quiet while it's merely overpaid, and comes back
if it turns `DENIED`, `UNDERPAID`, or `VANISHED`. `alerts.compute_raw_flags()` is the
resolution-blind variant the sweep and the snapshot both use; `compute_flags()` wraps it
with the suppression.

### Frontend (`frontend/src/`)

- React 19 + TypeScript + Vite; Tailwind for styling.
- `api.ts` — single typed API client; all calls go through the `req<T>()` helper which
  throws on non-2xx.
- `types.ts` — TypeScript interfaces mirroring the Pydantic schemas.
- TanStack Query for all server state; the `/api` prefix is proxied to `:8000` by Vite in
  dev. In the deployed build, FastAPI serves the built SPA itself (see Deployment) so
  there is no proxy — one origin on `:8000`.
- `context/YearContext.tsx` — global plan year state; wrap pages with `useYear()` to
  read/set.
- Pages: Dashboard, Submissions, SubmissionDetail, Matches, AnthemClaims,
  AnthemClaimDetail, Totals, Refresh, Settings.
- Dashboard has clickable per-flag count cards (Missing, Vanished, Denied, Stale Pending,
  Underpaid) that filter the alert list. The backend returns one alert per flag, but the
  page groups them by submission so each submission is a single row carrying all its flag
  badges; rows and badges stay severity-ordered (red → yellow → info).
- Submissions table exposes Match Status, Anthem Status, and Plan Paid from the linked
  anthem claim. Edit modal reuses `SubmissionModal` with pre-populated fields (amounts
  converted from cents to dollars). The "Hide resolved submissions" checkbox filters on
  `utils.isInterestingSubmission()`; rows hidden by it carry a gray "Resolved" or
  "Deprecated" badge when the filter is off.
- AnthemClaims table has Deductible and Coinsurance columns with a totals footer. Patient
  name links to a detail page showing all financials and the claim number.

### Automation (`automation/`)

Playwright scripts that log into Anthem and pull data. Dependencies are in the **backend
venv** (`playwright` and `requests` are in `backend/requirements.txt`) — no separate venv
needed.

- **`auth.py`** — `get_credentials()` resolves **env vars
  (`ANTHEM_USERNAME`/`ANTHEM_PASSWORD`) → macOS Keychain → interactive prompt**. The
  backend always injects the env vars when it spawns a script, so the Keychain step exists
  for manual runs (`python automation/submit_claim.py`), which would otherwise die with
  `EOFError` on the prompt when there's no TTY. `login(page, user, pass)` handles Anthem's
  Okta SSO (two-step: identifier → Next → password → submit → MFA wait). Browser opens
  non-headless for MFA. Session cookies persist in `data/browser-profile/` so MFA is only
  required once (until the Okta session expires).
- **`fetch_claims.py`** — navigates to the claims summary page, clicks Export, saves
  `data/exports/claims-YYYY-MM-DD-HHMM.csv`, POSTs to `/api/ingest/claims-csv`.
- **`fetch_benefits.py`** — navigates to the benefits page, reads `#ant-tab-body-1-0`
  (in-network) and `#ant-tab-body-1-1` (OON) directly by tab body ID. Extracts amounts
  from `.progress-bar-amount .label-text` spans and limits from
  `span:has-text("Your limit is $")`. POSTs to `/api/ingest/benefits`.
- **`fetch_all.py`** — single login, runs both scripts. Spawned by
  `POST /api/automation/run`.
- **`submit_claim.py`** — drives Anthem's claim-submission wizard through the PDF upload,
  then stops and hands the browser to the user (see Anthem claim filing). Reuses
  `auth.login()` and `auth.launch_context()`, so it shares the refresh flow's session and
  MFA. Inputs are `CLAIM_SUBMISSION_ID` / `CLAIM_MEMBER` / `CLAIM_PDF_PATH` /
  `CLAIM_DRY_RUN` env vars. Spawned by `POST /api/submissions/{id}/file-with-anthem/run`.

**Selector maintenance:** If Anthem changes their UI, update `_EXPORT_SELECTORS` in
`fetch_claims.py`, the tab/amount selectors in `fetch_benefits.py`, or the
`_MEDICAL_GET_STARTED` / `_PATIENT_SELECT` / `_PATIENT_TRIGGER` / `_UPLOAD_BUTTON`
constants (and the `_wait_for_page` heading needles) in `submit_claim.py`. Every failure
message names the file and constant to edit.

### Credentials (macOS Keychain)

- Anthem credentials live in the **macOS Keychain**, not in the UI.
  `backend/app/credentials.py` reads/writes two items under service
  `claims-tracker-anthem` via the `keyring` library; `get_credentials()` returns
  `(username, password)` or `None`.
- Set/change them with the terminal-only script `deploy/store_credentials.py`
  (`backend/.venv/bin/python deploy/store_credentials.py`) — credentials never traverse
  the web layer.
- `automation.py:run_automation()` resolves creds via `_resolve_credentials()` (passed-in
  args first, else Keychain) and injects them as `ANTHEM_USERNAME`/`ANTHEM_PASSWORD` env
  vars into the subprocess. The backend never logs or stores them.
- The Anthropic API key lives in a **separate Keychain service**
  (`claims-tracker-anthropic`), set with
  `backend/.venv/bin/python deploy/store_credentials.py --anthropic`. Settings shows its
  configured status read-only — the key never crosses the web layer.

### Refresh page / automation UX

- The Refresh page is a single **"Refresh Now"** button (no credential inputs) that POSTs
  an empty body to `/api/automation/run`; creds come from the Keychain.
- On failure, `automation.py:notify()` fires a native macOS notification (`osascript`).
  `_classify_failure()` distinguishes an **MFA-needed** failure (auth-step timeout) from a
  generic failure.
- After a run, stdout/stderr from the script is shown in the UI so failures are visible.
- **One browser job at a time.** The refresh, escalation and claim-filing jobs all run
  headfully out of a shared browser profile and share `_any_running()`, so a second job is
  refused with a 202 + `{"detail": "Automation already running"}`. A claim-filing run can
  hold that lock for up to 30 minutes (it waits out the user's 15-minute handoff), which
  means a daily refresh firing inside that window is skipped until its next tick. A
  crashed job auto-clears after its timeout + `_STALE_MARGIN_S`.
- The app runs over plain HTTP on localhost, which is acceptable for local-only use. The
  only plaintext-over-localhost surface is the CSV upload (no credentials). If ever
  exposed beyond localhost, add TLS.

### Data directory

`data/` is gitignored and holds the SQLite DB (`data/claims.db`), PDF uploads
(`data/pdfs/`), automation state (`data/state.json`, `data/escalation_state.json`,
`data/claim_filing_state.json`), browser session (`data/browser-profile/`), Playwright
exports (`data/exports/`), failure screenshots (`data/ih_last_error.png`,
`data/claim_filing_last_error.png`), and deployment logs (`data/logs/`).

### Deployment (`deploy/`)

Runs as an **always-on local macOS service**; not cloud. User-facing install/runbook lives
in the repo `README.md` (Manual setup + Tips sections).

- **`backend/app/static_serve.py`** — `create_spa_router(dist)` serves the built
  `frontend/dist` (catch-all GET: existing file → file, otherwise `index.html`; `api/*` →
  404). `main.py` includes it only when `frontend/dist` exists, so `npm run dev` and the
  test suite are unaffected.
- **`install.sh`** builds the frontend and installs two `launchd` LaunchAgents (templates
  rendered with the absolute repo root replacing `@@ROOT@@`); `uninstall.sh` removes them.
  - `com.claimstracker.server` — `uvicorn` on `127.0.0.1:8000` with `KeepAlive`; serves
    API + SPA. Logs → `data/logs/server.log`.
  - `com.claimstracker.refresh` — `StartInterval 86400` (once/day) runs `refresh.sh` →
    `POST /api/automation/run`. Logs → `data/logs/refresh.log`.
- **Scheduling model ("Option A"):** the laptop is often closed, so a daily run that's
  missed during sleep fires shortly after wake (launchd catch-up). No `pmset` scheduled
  wake.
- **MFA constraint:** scheduled runs use the headful browser, so they can only open it
  while the Mac is **logged in** (locked/asleep display is fine; logged out is not). When
  the Okta session expires, the run fails, a macOS notification fires, and the user
  completes MFA once via the Refresh page.
- **Trigger on demand:** `launchctl start com.claimstracker.refresh` (and
  `launchctl kickstart -k gui/$(id -u)/com.claimstracker.server` to restart the server).
