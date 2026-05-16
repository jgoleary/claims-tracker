# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

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
2. Playwright automation (`automation/fetch_all.py`, not yet built) or manual CSV upload ingests Anthem's export → upserted into `anthem_claims` table.
3. Matching algorithm links submissions ↔ anthem_claims via the `matches` table.
4. Alert flags are computed on-read (not stored) from the match state.

### Backend (`backend/app/`)
- **FastAPI** app in `main.py`; all routes mounted under `/api`.
- **SQLite** via SQLAlchemy 2.x; `database.py` holds the engine and `get_db()` dependency; schema auto-creates on startup via `init_db()`.
- **All money is integer cents** — never floats. `ingest.py:_parse_money()` converts `"$1,190.00"` → `119000`.
- **`models.py`** — five tables: `submissions`, `anthem_claims`, `matches`, `provider_aliases`, `benefits_snapshots`.
- **`matching.py`** — `run_matching()` is called after every CSV ingest and produces auto-matches + suggestions. Three-tier logic: (1) exact/prefix/alias provider match → auto; (2) member+date match but no provider → suggestion; (3) ambiguous multi-match → suggestion.
- **`alerts.py`** — `compute_flags(submission, match)` returns a list of `Alert` dataclasses. Thresholds live in `config.py` (MISSING_DAYS=30, STALE_PENDING_DAYS=45, UNDERPAID_MIN_CENTS=$25, UNDERPAID_PCT=10%).
- **`ingest.py`** — `ingest_claims_csv()` parses the Anthem CSV (BOM-safe via `utf-8-sig`, handles `"Not Available"` dates, `"$1,190.00"` money), upserts anthem_claims, then calls `run_matching()`. `ingest_benefits()` inserts a `BenefitsSnapshot` row per network. Anthem's export uses `Claim Number`, `Claim Type`, `Provided By`, and `Claim Received` — the parser accepts both those names and legacy alternatives.
- **`storage.py`** — `Storage` ABC with `LocalFileStorage` impl. PDF files stored under `data/pdfs/`. The `pdf_path` column is a storage key, not a raw filesystem path. Swap to S3 by implementing `Storage` and calling `set_storage()`.
- **`automation.py`** — thin wrapper that runs `automation/fetch_all.py` as a subprocess in a background thread and tracks status in `data/state.json`. This is how the "Refresh Now" button in the UI triggers the Playwright script.

### Provider alias learning
When the user confirms a match suggestion (`match_type="confirmed"`), `routes/matches.py` automatically writes a `ProviderAlias` row mapping `normalize(submission.provider_name)` → `normalize(claim.provider_name)`. Future matching uses these aliases for auto-matching, so confirming once means future claims from that provider auto-match.

### Frontend (`frontend/src/`)
- React 19 + TypeScript + Vite; Tailwind for styling.
- `api.ts` — single typed API client; all calls go through the `req<T>()` helper which throws on non-2xx.
- `types.ts` — TypeScript interfaces mirroring the Pydantic schemas.
- TanStack Query for all server state; the `/api` prefix is proxied to `:8000` by Vite.
- Pages map 1:1 to the nav items: Dashboard, Submissions, SubmissionDetail, Matches, AnthemClaims, Totals, Refresh, Settings.

### Automation (`automation/`)
Playwright scripts that log into Anthem and pull data. Install deps with `pip install -r automation/requirements.txt && playwright install chromium`.

- **`auth.py`** — `get_credentials()` reads `ANTHEM_USERNAME`/`ANTHEM_PASSWORD` env vars, falls back to interactive prompts. `login(page, user, pass)` fills the form and waits up to 120 s for MFA completion (browser opens non-headless so the user can interact).
- **`fetch_claims.py`** — navigates to the claims summary page, clicks Export, saves `data/exports/claims-YYYY-MM-DD-HHMM.csv`, POSTs to `/api/ingest/claims-csv`. Run standalone: `python automation/fetch_claims.py`.
- **`fetch_benefits.py`** — navigates to the benefits page, switches In-Network/Out-of-Network tabs, scrapes deductible and OOP spent/limit pairs, saves `data/exports/benefits-YYYY-MM-DD-HHMM.json`, POSTs to `/api/ingest/benefits`. Selectors use a two-strategy approach: labeled row lookup → full-page text regex fallback.
- **`fetch_all.py`** — single login, runs both scripts. This is what `POST /api/automation/run` spawns (via `backend/app/automation.py`). Exit code 0 = success, 1 = partial failure.

**Selector maintenance:** If Anthem changes their UI, update `_EXPORT_SELECTORS` in `fetch_claims.py` or `_IN_NETWORK_TAB`/`_OON_TAB`/`_find_row_amounts` in `fetch_benefits.py`. Both files have comments pointing to the relevant spots.

### Data directory
`data/` is gitignored and holds the SQLite DB (`data/claims.db`), PDF uploads (`data/pdfs/`), automation state (`data/state.json`), and Playwright CSV/benefits exports (`data/exports/`).
