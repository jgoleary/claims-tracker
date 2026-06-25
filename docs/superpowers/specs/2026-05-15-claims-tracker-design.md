# Claims Tracker — Design Doc

_Date: 2026-05-15_

## What We're Building

A local web app to track OON medical claims submitted to Anthem, reconcile them against
Anthem's data, and surface processing problems (missing claims, denials, stale pending,
underpayment). The app can trigger an Anthem data refresh through the UI by spawning a
Playwright browser automation script.

---

## Decisions Made During Brainstorming

| Topic                | Decision                                                                               |
| -------------------- | -------------------------------------------------------------------------------------- |
| WRONG_NETWORK flag   | Out of scope for v1 entirely — not stubbed, not mentioned in code                      |
| Plan year config     | `config.py` constants alongside other thresholds (30/45 days, $25, 10%)                |
| Ingest log           | No table — Refresh page shows automation run status only                               |
| Build order          | Option A: data layer first (models → matching engine → routes → UI)                    |
| Dashboard layout     | Alert Feed — severity badge filters at top, flat flagged-claims list below             |
| UI-triggered refresh | Yes — `POST /api/automation/run` spawns `fetch_all.py`; UI shows spinner + done/failed |
| Refresh UI feedback  | Spinner + counts on success / error message on failure. No live streaming.             |
| Frontend state       | React Query — no Redux/Zustand                                                         |
| Frontend tests       | None for v1                                                                            |
| Backend tests        | pytest with in-memory SQLite; no DB mocking                                            |

---

## Architecture

Three processes, one repo:

```
claims-tracker/
  backend/          # FastAPI, port 8000
    app/
      models.py     # SQLAlchemy ORM models
      schemas.py    # Pydantic request/response schemas
      matching.py   # Pure Python matching engine (no FastAPI dep)
      ingest.py     # CSV + benefits JSON parsing and DB writes
      storage.py    # Storage interface (local filesystem in v1)
      config.py     # Thresholds and plan year constants
      automation.py # Subprocess runner for Playwright scripts
      routes/
        submissions.py
        anthem_claims.py
        matches.py
        ingest.py
        dashboard.py
        totals.py
        providers.py
        automation.py
    tests/
  frontend/         # Vite + React + TypeScript + Tailwind, port 5173
  automation/       # Playwright scripts
    fetch_claims.py
    fetch_benefits.py
    fetch_all.py
  data/             # gitignored: SQLite DB, PDF storage, CSV/JSON exports, state.json
  docs/
```

**Backend:** FastAPI + SQLite via SQLAlchemy. Single process. API-only — no static file
serving in dev. In prod, could serve the built frontend bundle.

**Frontend:** Vite dev server proxies `/api` to `localhost:8000`. Built output is a static
bundle.

**Automation:** Standalone Python scripts, run manually or triggered via the UI.
Credentials are never stored — the user types them into the Chromium window directly.
`data/state.json` tracks last run state (`{status, last_run_at, summary}`) for persistence
across backend restarts.

**Storage interface:** `storage.py` wraps filesystem access for PDFs. The `pdf_path` field
on submissions is a storage key, not a raw filesystem path. Swappable to S3-compatible
storage later.

---

## Data Model

All money fields stored as integer cents. Five tables:

### `submissions`

One row per bill submitted to Anthem.

| field                  | type          | notes                                      |
| ---------------------- | ------------- | ------------------------------------------ |
| id                     | uuid pk       |                                            |
| member_name            | text          | freeform; matching is case-insensitive     |
| provider_name          | text          | canonical name as I know it                |
| service_date           | date          | first date of service on the bill          |
| amount_billed          | int cents     |                                            |
| expected_reimbursement | int cents     |                                            |
| network_treatment      | enum          | `in_network_exception` \| `out_of_network` |
| submitted_date         | date          |                                            |
| submission_method      | enum          | `portal` \| `email`                        |
| pdf_path               | text nullable | storage key                                |
| notes                  | text nullable |                                            |
| created_at             | timestamp     |                                            |
| updated_at             | timestamp     |                                            |

### `anthem_claims`

Imported from CSV. Upserted by `claim_number`. Rows are never deleted — `last_seen_at`
goes stale if a claim disappears from the CSV.

| field              | type          | notes                                        |
| ------------------ | ------------- | -------------------------------------------- |
| claim_number       | text pk       |                                              |
| claim_type         | text          | `Medical` \| `Pharmacy`                      |
| patient_name       | text          | parsed from "Name (YYYY-MM-DD)"; DOB dropped |
| service_date       | date          |                                              |
| received_date      | date nullable |                                              |
| processed_date     | date nullable |                                              |
| status             | enum          | `Pending` \| `Approved` \| `Denied`          |
| provider_name      | text          | as Anthem has it; may be truncated           |
| billed             | int cents     |                                              |
| plan_discount      | int cents     |                                              |
| allowed            | int cents     |                                              |
| plan_paid          | int cents     |                                              |
| additional_savings | int cents     |                                              |
| deductible         | int cents     |                                              |
| coinsurance        | int cents     |                                              |
| copay              | int cents     |                                              |
| not_covered        | int cents     |                                              |
| your_cost          | int cents     |                                              |
| first_seen_at      | timestamp     |                                              |
| last_seen_at       | timestamp     | updated on every ingest                      |

### `matches`

Links a submission to an anthem_claim. A submission has at most one match.

| field               | type           | notes                             |
| ------------------- | -------------- | --------------------------------- |
| submission_id       | uuid fk unique |                                   |
| anthem_claim_number | text fk        |                                   |
| match_type          | enum           | `auto` \| `confirmed` \| `manual` |
| confirmed_at        | timestamp      |                                   |

### `provider_aliases`

Learned mapping from canonical provider name to Anthem's name.

| field          | type      | notes                |
| -------------- | --------- | -------------------- |
| canonical_name | text      | normalized lowercase |
| anthem_name    | text      | normalized lowercase |
| confirmed_at   | timestamp |                      |

UNIQUE(canonical_name, anthem_name).

Network bucket for the totals rollup is computed at query time, not stored: for matched
claims, use `submission.network_treatment` (mapping `in_network_exception` →
`in_network`); for unmatched anthem_claims, default to `in_network`. This is computed in
`GET /api/totals`.

### `benefits_snapshots`

One row per network per ingest of the benefits page.

| field            | type      | notes                            |
| ---------------- | --------- | -------------------------------- |
| id               | int pk    |                                  |
| snapshot_date    | timestamp |                                  |
| network          | enum      | `in_network` \| `out_of_network` |
| deductible_limit | int cents |                                  |
| deductible_spent | int cents |                                  |
| oop_limit        | int cents |                                  |
| oop_spent        | int cents |                                  |

---

## Matching Engine (`matching.py`)

Pure Python module — no FastAPI dependency. Testable in isolation. Returns result objects;
callers own DB writes.

Runs after every CSV ingest and after every new submission is created. Operates on
unmatched submissions only.

**Normalization:** single `normalize(s)` function — lowercase, strip/collapse whitespace,
strip non-alphanumeric except spaces. Used everywhere names are compared.

**Tier 1 — auto-match:** member name + service date + provider all match (exact, prefix,
or known alias). If exactly one candidate → `match_type='auto'`. If multiple candidates on
either side → escalate to Tier 2.

**Tier 2 — suggested:** member + service date match, provider doesn't. Surfaced via
`GET /api/matches/suggestions`. Confirming creates a `provider_alias` row and a
`match_type='confirmed'` match.

**Tier 3 — manual:** user searches anthem_claims and forces a match.
`match_type='manual'`.

---

## Alert Rules (`config.py` thresholds)

Computed on read, not stored. Applied per submission.

| flag               | condition                                                     | severity |
| ------------------ | ------------------------------------------------------------- | -------- |
| MISSING            | unmatched AND submitted_date < today − 30 days                | red      |
| STALE_PENDING      | status=Pending AND received_date < today − 45 days            | yellow   |
| DENIED             | status=Denied                                                 | red      |
| UNDERPAID          | status=Approved AND abs(expected − plan_paid) > max($25, 10%) | yellow   |
| APPROVED_ZERO_PAID | status=Approved AND plan_paid=0 AND your_cost > 0             | info     |

Thresholds in `config.py`: `MISSING_DAYS = 30`, `STALE_DAYS = 45`,
`UNDERPAID_MIN_DOLLARS = 25_00`, `UNDERPAID_PCT = 0.10`.

---

## API

All routes under `/api`. FastAPI, JSON.

### Submissions

- `GET /api/submissions` — list; query params: `member`, `status`, `flag`, `from_date`,
  `to_date`
- `POST /api/submissions` — create
- `GET /api/submissions/{id}` — detail with matched claim and computed flags
- `PATCH /api/submissions/{id}` — edit
- `DELETE /api/submissions/{id}` — delete and unmatch
- `POST /api/submissions/{id}/pdf` — upload PDF (multipart)
- `GET /api/submissions/{id}/pdf` — download PDF

### Anthem Claims

- `GET /api/anthem-claims` — list; query params: `matched`, `status`, `patient`
- `GET /api/anthem-claims/{claim_number}` — detail

### Matches

- `GET /api/matches/suggestions` — list of (submission, [candidates]) pairs
- `POST /api/matches` — body `{submission_id, anthem_claim_number, match_type}`
- `DELETE /api/matches/{submission_id}` — unmatch

### Ingest

- `POST /api/ingest/claims-csv` — multipart CSV upload; parses, upserts, re-runs matching;
  returns `{new, updated, auto_matched, suggestions}`
- `POST /api/ingest/benefits` — JSON body with scraped benefits data

### Dashboard

- `GET /api/dashboard` —
  `{counts: {missing, stale_pending, denied, underpaid}, alerts: [...]}`

### Totals

- `GET /api/totals` — latest benefits snapshot per network + CSV rollup per network + diff

### Automation

- `POST /api/automation/run` — spawns `fetch_all.py` subprocess; returns 202. No-op if
  already running.
- `GET /api/automation/status` —
  `{status: idle|running|complete|failed, last_run_at, summary}`

### Providers

- `GET /api/providers/aliases`
- `DELETE /api/providers/aliases/{id}`

---

## Frontend Pages

React + TypeScript + Vite + Tailwind. React Query for all server state.

1. **Dashboard** (`/`) — severity badge filters (MISSING, DENIED, STALE, UNDERPAID) at
   top, flat alert list below sorted by severity then date. "Refresh" button top-right
   triggers automation run; shows spinner while running, counts on success.
2. **Submissions** (`/submissions`) — table with filters, "Add submission" modal.
3. **Submission detail** (`/submissions/:id`) — full record, PDF viewer/download, matched
   claim side-by-side, edit/delete/rematch actions.
4. **Match review** (`/matches`) — shown when suggestions exist. Submission card +
   candidate claim card(s). Confirm / Not a match / Search for different claim.
5. **Anthem claims** (`/anthem-claims`) — read-only table with matched/unmatched
   indicator.
6. **Totals** (`/totals`) — In-Network and OON cards; deductible and OOP from benefits
   page vs CSV rollup; diff highlighted if > threshold.
7. **Refresh** (`/refresh`) — "Refresh Now" button (same as dashboard), run status, manual
   CSV/benefits upload as fallback.
8. **Settings** (`/settings`) — provider aliases list with delete; threshold display
   (read-only in v1, edit `config.py` directly).

---

## Automation Scripts

`automation/fetch_claims.py` — opens Chromium non-headless, user logs in and completes MFA
manually, navigates to claims summary, triggers Export, downloads CSV to
`data/exports/claims-YYYY-MM-DD-HHMM.csv`, POSTs to `/api/ingest/claims-csv` or prints
curl.

`automation/fetch_benefits.py` — same login flow, scrapes benefits page for deductible/OOP
numbers per network tab, writes `data/exports/benefits-YYYY-MM-DD-HHMM.json`, POSTs to
`/api/ingest/benefits` or prints curl.

`automation/fetch_all.py` — runs both scripts, reuses browser session so MFA is only
needed once.

Credentials are never stored. The Chromium window opens on the local machine; the user
types credentials directly into the browser.

---

## Testing

- **Backend:** pytest with in-memory SQLite. No DB mocking. Heavy coverage on
  `matching.py` (normalization, all three tiers, alias learning, conflict resolution) and
  `ingest.py` (CSV quirks: BOM, money parsing, date nulls, patient name parsing). Route
  tests use FastAPI `TestClient`.
- **Frontend:** manual testing against real data in v1. No automated UI tests.

---

## Out of Scope for v1

- WRONG_NETWORK flag (not stubbed — add later if needed)
- Denial reason extraction (requires per-claim detail page scraping)
- Email/push notifications
- Multi-user, multi-account
- Cloud hosting (Storage interface seam is there)
- OCR on bill PDFs
- Editable thresholds in the UI (edit `config.py` directly)
- Ingest history log
