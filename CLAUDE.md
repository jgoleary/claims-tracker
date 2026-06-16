# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
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
2. Playwright automation (`automation/fetch_all.py`) or manual CSV upload ingests Anthem's export → upserted into `anthem_claims` table.
3. Matching algorithm links submissions ↔ anthem_claims via the `matches` table. Matching runs automatically after every CSV ingest, submission create, and submission update.
4. Alert flags are computed on-read (not stored) from the match state.

### Backend (`backend/app/`)
- **FastAPI** app in `main.py`; all routes mounted under `/api`.
- **SQLite** via SQLAlchemy 2.x; `database.py` holds the engine and `get_db()` dependency; schema auto-creates on startup via `init_db()`.
- **All money is integer cents** — never floats. `ingest.py:_parse_money()` converts `"$1,190.00"` → `119000`.
- **`models.py`** — five tables: `submissions`, `anthem_claims`, `matches`, `provider_aliases`, `benefits_snapshots`.
- **`matching.py`** — `run_matching()` is called after every CSV ingest, submission create, and submission update. Three-tier logic: (1) exact/prefix/alias provider match → auto; (2) member+date match but no provider → suggestion; (3) ambiguous multi-match → suggestion.
- **`alerts.py`** — `compute_flags(submission, match, latest_ingest_at=None)` returns a list of `Alert` dataclasses. Thresholds live in `config.py` (MISSING_DAYS=30, STALE_PENDING_DAYS=30, UNDERPAID_MIN_CENTS=$25, UNDERPAID_PCT=10%). `APPROVED_ZERO_PAID` flag is suppressed when `expected_reimbursement == 0`. The `VANISHED` flag (red) fires when a matched claim's `last_seen_at` predates `latest_ingest_at` (= `max(last_seen_at)` across all anthem_claims, supplied by `routes/submissions.latest_ingest_at(db)`) — i.e. the claim dropped out of Anthem's latest export. Ingest is upsert-only and never deletes vanished claims, so this is how a disappeared-but-still-matched claim gets surfaced.
- **`ingest.py`** — `ingest_claims_csv()` parses the Anthem CSV (BOM-safe via `utf-8-sig`, handles `"Not Available"` dates, `"$1,190.00"` money), upserts anthem_claims, then calls `run_matching()`. `_parse_date()` accepts both ISO (`2026-05-26`) and Anthem's display format (`May 26, 2026`) — the `/member/claims` export uses the display format. `ingest_benefits()` inserts a `BenefitsSnapshot` row per network. Anthem's export uses `Claim Number`, `Claim Type`, `Provided By`, and `Claim Received` — the parser accepts both those names and legacy alternatives. `_parse_patient_name()` canonicalizes the `Patient` field (`"Nolan O'leary (2019-02-14)"`) to the **first name only** (`"Nolan"`) — Anthem exports the name inconsistently (`"First Last"` vs `"First"`) across exports, so the surname/DOB are dropped to keep one person from fragmenting into multiple `patient_name` values. Matching compares on first name (`matching.py:_first_name`) so full-name submissions still link to first-name claims.
- **`storage.py`** — `Storage` ABC with `LocalFileStorage` impl. PDF files stored under `data/pdfs/`. The `pdf_path` column is a storage key, not a raw filesystem path. Swap to S3 by implementing `Storage` and calling `set_storage()`.
- **`automation.py`** — runs `automation/fetch_all.py` as a subprocess (using `sys.executable` so it shares the backend venv) in a background thread, tracking status in `data/state.json`. Accepts `username`/`password` and passes them as env vars to the subprocess — credentials are never written to disk.
- **`config.py`** — `plan_year_dates(year: int) -> (date, date)` returns Jan 1 / Dec 31 for any calendar year. All list/totals endpoints accept a `year` query param (defaults to current year).

### Plan year filtering
Every data endpoint (`/submissions`, `/anthem-claims`, `/dashboard`, `/totals`) accepts `?year=YYYY` and filters by `service_date`. The frontend stores the selected year in `YearContext` and passes it to all queries. The sidebar dropdown sets it globally.

### Totals logic
- CSV rollup sums `deductible + coinsurance` from `anthem_claims` for the selected plan year.
- **In-network spending counts toward both the in-network and OON accumulators** — in-network claims are added to both buckets in `_get_csv_rollup`.
- The Totals page shows spent, remaining (= limit − spent), and diff vs. CSV sum for each network.

### Provider alias learning
When the user confirms a match suggestion (`match_type="confirmed"`), `routes/matches.py` automatically writes a `ProviderAlias` row mapping `normalize(submission.provider_name)` → `normalize(claim.provider_name)`. Future matching uses these aliases for auto-matching.

### Frontend (`frontend/src/`)
- React 19 + TypeScript + Vite; Tailwind for styling.
- `api.ts` — single typed API client; all calls go through the `req<T>()` helper which throws on non-2xx.
- `types.ts` — TypeScript interfaces mirroring the Pydantic schemas.
- TanStack Query for all server state; the `/api` prefix is proxied to `:8000` by Vite.
- `context/YearContext.tsx` — global plan year state; wrap pages with `useYear()` to read/set.
- Pages: Dashboard, Submissions, SubmissionDetail, Matches, AnthemClaims, AnthemClaimDetail, Totals, Refresh, Settings.
- Submissions table exposes Match Status, Anthem Status, and Plan Paid from the linked anthem claim. Edit modal reuses `SubmissionModal` with pre-populated fields (amounts converted from cents to dollars).
- AnthemClaims table has Deductible and Coinsurance columns with a totals footer. Patient name links to a detail page showing all financials and the claim number.

### Automation (`automation/`)
Playwright scripts that log into Anthem and pull data. Dependencies are in the **backend venv** (`playwright` and `requests` are in `backend/requirements.txt`) — no separate venv needed.

- **`auth.py`** — `get_credentials()` reads `ANTHEM_USERNAME`/`ANTHEM_PASSWORD` env vars first, then falls back to interactive prompts. `login(page, user, pass)` handles Anthem's Okta SSO (two-step: identifier → Next → password → submit → MFA wait). Browser opens non-headless for MFA. Session cookies persist in `data/browser-profile/` so MFA is only required once.
- **`fetch_claims.py`** — navigates to the claims summary page, clicks Export, saves `data/exports/claims-YYYY-MM-DD-HHMM.csv`, POSTs to `/api/ingest/claims-csv`.
- **`fetch_benefits.py`** — navigates to the benefits page, reads `#ant-tab-body-1-0` (in-network) and `#ant-tab-body-1-1` (OON) directly by tab body ID. Extracts amounts from `.progress-bar-amount .label-text` spans and limits from `span:has-text("Your limit is $")`. POSTs to `/api/ingest/benefits`.
- **`fetch_all.py`** — single login, runs both scripts. Spawned by `POST /api/automation/run`.

**Selector maintenance:** If Anthem changes their UI, update `_EXPORT_SELECTORS` in `fetch_claims.py` or the tab/amount selectors in `fetch_benefits.py`.

### Refresh page / automation UX
- Username and password are entered in the Refresh page UI each time — never persisted anywhere.
- They're POSTed to `/api/automation/run` and passed as env vars (`ANTHEM_USERNAME`, `ANTHEM_PASSWORD`) to the subprocess. The backend never logs or stores them.
- After a run, stdout/stderr from the script is shown in the UI so failures are visible.
- The app runs over plain HTTP on localhost, which is acceptable for local-only use. If ever exposed beyond localhost, add TLS.

### Data directory
`data/` is gitignored and holds the SQLite DB (`data/claims.db`), PDF uploads (`data/pdfs/`), automation state (`data/state.json`), browser session (`data/browser-profile/`), and Playwright exports (`data/exports/`).
