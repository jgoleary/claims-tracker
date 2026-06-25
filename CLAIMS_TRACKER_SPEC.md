# Claims Tracker — Spec

A local web app to track OON medical claims submitted to Anthem, reconcile them against
Anthem's data, and surface processing problems (missing claims, discrepancies, denials).

## Goals

1. Record each OON bill I submit to Anthem (member, provider, first date of service,
   billed amount, expected reimbursement, submission method, PDF of the bill). One
   submission = one bill = one Anthem claim.
2. Pull Anthem's view of my claims (status, processed date, plan paid, etc.) via a
   Playwright script that exports the claims CSV and scrapes the benefits page.
3. Match my submissions to Anthem's claims and flag problems:
   - MISSING: I submitted >30 days ago, no record on Anthem's side.
   - PENDING too long (>45 days).
   - DENIED.
   - Plan paid materially differs from expected reimbursement.
   - Wrong network treatment (I expected in-network exception, Anthem processed OON).
4. Show running deductible/OOP totals from the Anthem benefits page alongside the sum of
   `deductible + coinsurance` columns from the claims CSV, to spot accounting drift.

## Stack

- **Backend**: Python (FastAPI) + SQLite + SQLAlchemy. Single-process, runs locally.
  Designed to be cloud-hostable later (no hard-coded filesystem assumptions for PDFs —
  wrap in a storage interface).
- **Frontend**: React + TypeScript + Vite + Tailwind. Calls the FastAPI backend via fetch.
- **Automation**: Playwright (Python) in a separate `automation/` directory. Runs locally
  on demand; outputs `claims.csv` and `benefits.json` to a known directory the backend
  ingests.
- **PDF storage**: Local filesystem in v1, behind a `Storage` interface that can swap to
  S3-compatible object storage for cloud hosting.

Project layout:

```
claims-tracker/
  backend/        # FastAPI app
    app/
      models.py
      schemas.py
      routes/
      matching.py
      ingest.py
      storage.py
    tests/
  frontend/       # Vite/React/TS
  automation/     # Playwright scripts
    fetch_claims.py
    fetch_benefits.py
  data/           # gitignored: sqlite db, csv exports, pdf storage
  README.md
```

## Data model

All money fields stored as integer cents to avoid float issues.

### `submissions`

One row per bill submitted to Anthem. A bill may contain multiple line items / sessions,
but is always one provider and one member. Anthem processes each bill as a single claim.

| field                  | type          | notes                                                                                    |
| ---------------------- | ------------- | ---------------------------------------------------------------------------------------- |
| id                     | uuid pk       |                                                                                          |
| member_name            | text          | freeform; matching is case-insensitive                                                   |
| provider_name          | text          | the canonical name as I know it                                                          |
| service_date           | date          | the **first** date of service on the bill. Anthem uses this as the claim's Service Date. |
| amount_billed          | int (cents)   | total billed across all line items on the bill                                           |
| expected_reimbursement | int (cents)   | what I expect Anthem to pay me back; I compute this myself                               |
| network_treatment      | enum          | `in_network_exception` \| `out_of_network`                                               |
| submitted_date         | date          | when I submitted to Anthem                                                               |
| submission_method      | enum          | `portal` \| `email`                                                                      |
| pdf_path               | text nullable | storage key, not raw filesystem path                                                     |
| notes                  | text nullable |                                                                                          |
| created_at             | timestamp     |                                                                                          |
| updated_at             | timestamp     |                                                                                          |

### `anthem_claims`

Imported fresh from each CSV ingest. Keyed on `claim_number` (Anthem's unique ID).
Re-imports upsert by claim_number; existing rows update their fields, new rows insert.
Don't delete rows that disappear from the CSV — instead, leave them with
`last_seen_in_csv` going stale (could indicate a claim reversal worth flagging,
low-priority).

| field              | type          | notes                                                   |
| ------------------ | ------------- | ------------------------------------------------------- |
| claim_number       | text pk       | from Anthem                                             |
| claim_type         | text          | `Medical` \| `Pharmacy`                                 |
| patient_name       | text          | parsed from "Name (YYYY-MM-DD)" column; drop DOB        |
| service_date       | date          |                                                         |
| received_date      | date nullable |                                                         |
| processed_date     | date nullable |                                                         |
| status             | enum          | `Pending` \| `Approved` \| `Denied` (normalize casing)  |
| provider_name      | text          | as Anthem has it; may be truncated (~25 chars) or wrong |
| billed             | int cents     |                                                         |
| plan_discount      | int cents     |                                                         |
| allowed            | int cents     |                                                         |
| plan_paid          | int cents     |                                                         |
| additional_savings | int cents     |                                                         |
| deductible         | int cents     |                                                         |
| coinsurance        | int cents     |                                                         |
| copay              | int cents     |                                                         |
| not_covered        | int cents     |                                                         |
| your_cost          | int cents     |                                                         |
| first_seen_at      | timestamp     |                                                         |
| last_seen_at       | timestamp     | updated on every ingest where this claim_number appears |

### `matches`

Links a submission to an anthem_claim. A submission has at most one match.

| field               | type           | notes                                                                                          |
| ------------------- | -------------- | ---------------------------------------------------------------------------------------------- |
| submission_id       | uuid fk unique |                                                                                                |
| anthem_claim_number | text fk        |                                                                                                |
| match_type          | enum           | `auto` \| `confirmed` (user confirmed a suggested match) \| `manual` (user picked from search) |
| confirmed_at        | timestamp      |                                                                                                |

### `provider_aliases`

Learned mapping from my canonical name to Anthem's name. Used so future matches don't
require re-confirmation.

| field          | type      | notes                |
| -------------- | --------- | -------------------- |
| canonical_name | text      | normalized lowercase |
| anthem_name    | text      | normalized lowercase |
| confirmed_at   | timestamp |                      |

UNIQUE(canonical_name, anthem_name).

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

## Matching algorithm

Run on every CSV ingest, and on every new submission.

For each unmatched submission, find candidate Anthem claims that are also unmatched:

**Tier 1 — auto-match.** All of:

- `submission.member_name` ≈ `claim.patient_name` (case-insensitive equality after
  normalization)
- `submission.service_date == claim.service_date`
- Provider matches by any of:
  - Exact match (case-insensitive, normalized whitespace)
  - Prefix match: one name is a prefix of the other after normalization (handles Anthem
    truncation at ~25 chars)
  - Known alias in `provider_aliases`

If exactly one Anthem claim matches → create `match` with `match_type='auto'`. If multiple
Anthem claims match one submission, OR multiple submissions match one Anthem claim → none
auto-match; surface them all as suggestions for manual disambiguation.

**Tier 2 — suggested match.** Member + service_date match but provider doesn't.

For each suggestion, the UI shows my submission side-by-side with the Anthem claim. When I
confirm, the app:

1. Creates a `match` row with `match_type='confirmed'`.
2. Adds a `provider_alias` row if not present (canonical = my submission's provider,
   anthem = the claim's provider). Future auto-matches use it.

**Tier 3 — manual.** I can also search Anthem claims and force a match (escape hatch).

### Normalization

- Lowercase
- Strip leading/trailing whitespace, collapse internal whitespace to single space
- Strip non-alphanumeric except spaces (so "St. Mary's" matches "St Marys")
- For prefix matching, compare with same normalization

## Discrepancy / alert rules

Computed on read, not stored. The dashboard surfaces these.

For each submission:

| flag               | condition                                                                                                                                                                                                                             | severity                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| MISSING            | matched=false AND submitted_date < today − 30 days                                                                                                                                                                                    | red                                               |
| STALE_PENDING      | match.status='Pending' AND received_date < today − 45 days                                                                                                                                                                            | yellow                                            |
| DENIED             | match.status='Denied'                                                                                                                                                                                                                 | red                                               |
| UNDERPAID          | match.status='Approved' AND abs(expected_reimbursement − plan_paid) > max($25, 10%)                                                                                                                                                   | yellow                                            |
| WRONG_NETWORK      | submission.network_treatment='in_network_exception' AND claim landed against OON bucket (heuristic: claim's deductible/coinsurance accumulated to OON totals — derived from comparing CSV sum delta vs benefits snapshot per network) | yellow                                            |
| APPROVED_ZERO_PAID | match.status='Approved' AND plan_paid=0 AND your_cost > 0                                                                                                                                                                             | info (usually = deductible, not really a problem) |

Thresholds (30, 45, $25, 10%) should be in a `config.py` constant, easy to tweak.

## Totals view

Two columns, In-Network and Out-of-Network. For each:

- **From benefits page**: deductible spent / limit, OOP spent / limit (latest snapshot).
- **From CSV rollup**: sum of `deductible + coinsurance` across claims whose network
  bucket = this column, scoped to current plan year.
  - For matched claims, network bucket = `submission.network_treatment`
    (in_network_exception → in_network bucket).
  - For unmatched Anthem claims (in-network medical I didn't submit), default to
    in_network.
  - Pharmacy claims: separate or include? V1: include in their assigned bucket.
- Difference, with a flag if > $50 (configurable).

## API

FastAPI, JSON. All routes under `/api`.

### Submissions

- `GET /api/submissions` — list. Query params: `member`, `status` (matched/unmatched/all),
  `flag` (filter to claims with a given flag), `from_date`, `to_date`.
- `POST /api/submissions` — create one submission.
- `GET /api/submissions/{id}` — detail, includes matched anthem_claim if any, and computed
  flags.
- `PATCH /api/submissions/{id}` — edit.
- `DELETE /api/submissions/{id}` — delete (also unmatches).
- `POST /api/submissions/{id}/pdf` — upload PDF (multipart). Stores via Storage interface.
- `GET /api/submissions/{id}/pdf` — download.

### Anthem claims

- `GET /api/anthem-claims` — list. Query: `matched` (true/false/all), `status`, `patient`.
- `GET /api/anthem-claims/{claim_number}` — detail.

### Matches

- `GET /api/matches/suggestions` — list of (submission, [candidate claims]) pairs awaiting
  confirmation.
- `POST /api/matches` — body `{submission_id, anthem_claim_number, match_type}`. Creates
  match + alias if applicable.
- `DELETE /api/matches/{submission_id}` — unmatch.

### Ingest

- `POST /api/ingest/claims-csv` — multipart CSV upload. Parses, upserts anthem_claims,
  re-runs matching, returns summary
  (`{new: n, updated: n, auto_matched: n, suggestions: n}`).
- `POST /api/ingest/benefits` — JSON body with the scraped benefits data. Inserts
  benefits_snapshots rows.

### Dashboard

- `GET /api/dashboard` — counts and the alert list. Returns:
  ```json
  {
    "counts": {"missing": 3, "stale_pending": 1, "denied": 2, "underpaid": 4},
    "alerts": [{"submission_id": "...", "flag": "MISSING", "details": {...}}, ...]
  }
  ```

### Totals

- `GET /api/totals` — current totals view data. Returns latest benefits_snapshot per
  network + CSV rollup per network + diff.

### Providers

- `GET /api/providers/aliases` — list (for a settings page).
- `DELETE /api/providers/aliases/{id}` — remove a learned alias if wrong.

## Frontend pages

1. **Dashboard** (`/`) — counts at top (clickable to filter), then the alert list grouped
   by severity (red, yellow, info). Each alert is a row showing the submission key facts +
   the flag reason + a "view" link. "Refresh data" button prominently at top right, with
   last-refresh timestamp.

2. **Submissions** (`/submissions`) — table with columns: member, provider, service date,
   billed, expected reimbursement, submitted date, status (matched + Anthem status or
   unmatched), plan paid, flags. Filters at top. "Add submission" button → modal for
   entering a single bill (member, provider, first DOS, billed total, expected
   reimbursement, network treatment, submission method, submitted date, optional PDF,
   notes).

3. **Submission detail** (`/submissions/:id`) — full record, PDF viewer/download, matched
   Anthem claim side-by-side if matched, edit/delete actions, change match action.

4. **Match review** (`/matches`) — only shows when suggestions exist. Each suggestion: my
   submission card on the left, candidate Anthem claim card on the right (or multiple
   candidates if there are several). "Confirm match" / "Not a match" / "Search for
   different claim" buttons. After confirm, auto-creates the alias.

5. **Anthem claims** (`/anthem-claims`) — read-only table of everything in the CSV import,
   with matched/unmatched indicator.

6. **Totals** (`/totals`) — the benefits-vs-CSV-rollup view. Two cards (In-Network, OON),
   each showing deductible spent (benefits page) vs deductible sum (CSV), OOP spent vs
   (deductible + coinsurance) sum. Diff highlighted if > threshold.

7. **Refresh** (`/refresh`) — instructions to run the Playwright script + manual
   CSV/benefits upload as fallback. Shows ingest history.

8. **Settings** (`/settings`) — provider aliases list with delete, threshold config,
   plan-year date range.

## Playwright automation

Two scripts in `automation/`. Both prompt for credentials at runtime (don't store).

### `fetch_claims.py`

1. Launches Chromium non-headless (so I can complete MFA if needed).
2. Navigates to login page, fills credentials, waits for me to complete MFA manually if
   prompted.
3. Navigates to `https://membersecure.anthem.com/member/claims/summary`.
4. Triggers the Export button, downloads CSV.
5. Saves to `data/exports/claims-YYYY-MM-DD-HHMM.csv`.
6. Prints the path + a curl command to POST it to the backend, OR (if backend is running)
   POSTs directly to `/api/ingest/claims-csv`.

### `fetch_benefits.py`

1. Same login flow (reuse the browser context if running back-to-back).
2. Navigates to `https://membersecure.anthem.com/member/benefits?covtype=med`.
3. Scrapes the four numbers per network (deductible spent/limit, OOP spent/limit), for
   in-network and out-of-network tabs.
4. Writes `data/exports/benefits-YYYY-MM-DD-HHMM.json`.
5. POSTs to `/api/ingest/benefits` or prints the curl.

Both scripts should be runnable individually and as a combined `fetch_all.py` wrapper.

## CSV parsing notes

Real-world quirks observed in the sample export:

- Header row may have a BOM; strip it.
- "Patient" column format: `"Nolan O'leary (2019-02-14)"`. Split on ` (` to get name;
  trailing `)`; drop DOB.
- Money columns may have `$` and commas: `"$1,190.00"`, sometimes quoted. Parse to cents.
- Date columns: `YYYY-MM-DD` or the literal string `"Not Available"` → null.
- Status values: `Pending`, `Approved`, `Denied`. Normalize casing.
- Provider names sometimes truncated at ~25 chars (e.g. "Joyful Behavior Therapy L",
  "California Pacific Medica"). Matching handles this via prefix matching.

## v1 acceptance

- [ ] Create a submission via the UI, upload a PDF.
- [ ] Run the Playwright script, ingest the CSV, see anthem_claims populated.
- [ ] An obvious match (same provider, same DOS, same member) auto-matches.
- [ ] A non-obvious match (Citrus Speech ↔ Test Purchase) appears as a suggestion;
      confirming it creates an alias; re-running ingest after a second submission for the
      same provider auto-matches via the alias.
- [ ] A submission with no Anthem claim and submitted_date > 30 days ago shows up as
      MISSING on the dashboard.
- [ ] Totals page shows benefits-page numbers next to CSV rollup with the diff.
- [ ] All money values display correctly (no float-rounding artifacts).

## Out of scope for v1

- Denial reason extraction (would require scraping the per-claim detail page).
- Email/push notifications for new alerts.
- Multi-user, multi-account.
- Cloud hosting (but the seams are there for it).
- OCR on the bill PDF to auto-populate the submission form.
