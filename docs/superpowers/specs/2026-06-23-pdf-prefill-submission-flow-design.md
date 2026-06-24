# PDF-Prefilled Submission Flow — Design

**Date:** 2026-06-23
**Status:** Approved design, pending implementation plan

## Goal

Change the Add Submission flow so the user can:

1. Upload a PDF and have most fields auto-filled by sending the PDF to Claude.
2. Have the **expected reimbursement** computed (not extracted) from the deductible
   remaining, the network, the coinsurance settings, and the out-of-pocket maximum.
3. Fall back gracefully to fully-manual entry when no Anthropic API key is configured
   or extraction fails.
4. On "Add Submission", create the local record and open Anthem's submission
   questionnaire in a new browser tab, then confirm — in the same modal — once the
   claim has actually been uploaded to Anthem.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Where extraction runs | Backend (Python `anthropic` SDK) — keeps the API key off the browser |
| Where expected is computed | Frontend (modal already loads benefits + plan config; recomputes live) |
| Expected formula | Deductible → coinsurance, capped at OOP remaining (unified `min()` form) |
| Confirm-to-Anthem flow | Same modal, two-step |
| Confirm data | Sets `submitted_date` (no separate flag); `submitted_date` becomes nullable |
| API key location | Env var `ANTHROPIC_API_KEY` (SDK default); set in launchd service env on deploy |
| Extraction model | `claude-sonnet-4-6` |
| Anthem URL | `https://membersecure.anthem.com/member/claims/submission-questionnaire` |

## Expected reimbursement computation

For a claim where the member paid the provider and is seeking reimbursement, the plan
pays everything above the remaining deductible, minus the coinsurance share, capped so
the member never pays more than their remaining out-of-pocket maximum:

```
deductible_applied = min(billed, deductible_remaining)
after_deductible   = billed − deductible_applied
member_oop         = min(deductible_applied + after_deductible × coinsurance_pct,
                         oop_remaining)
expected           = billed − member_oop
```

- Large OOP remaining → reduces to `after_deductible × (1 − coinsurance_pct)`.
- OOP remaining at zero → plan pays 100% (deductible is necessarily also exhausted).
- All money is integer cents. `coinsurance_pct` is a fraction (e.g. 0.30).

**Network selects the inputs:**

| `network_treatment` | Deductible remaining | Coinsurance % |
|---|---|---|
| `out_of_network` | OON benefits snapshot | `out_of_network_coinsurance_pct` |
| `in_network_exception` | in-network benefits snapshot | `in_network_coinsurance_pct` |

Deductible-remaining and OOP-remaining come per-network from the benefits snapshot the
modal already loads via `GET /api/totals` (`benefits.deductible_limit − deductible_spent`,
`benefits.oop_limit − oop_spent`). Coinsurance % comes from `GET /api/settings/plan-config`.

When the benefits snapshot for the selected network is missing, the modal cannot compute
a value — leave expected blank and let the user enter it manually.

## Components

### Backend

**`app/extraction.py`** (new)
- `ExtractionResult` dataclass / Pydantic model:
  `configured: bool`, `error: Optional[str]`,
  `member_name: Optional[str]`, `provider_name: Optional[str]`,
  `first_service_date: Optional[date]`, `amount_billed_cents: Optional[int]`.
- `extract_submission_fields(pdf_bytes: bytes) -> ExtractionResult`:
  - If `ANTHROPIC_API_KEY` is unset → return `ExtractionResult(configured=False)`.
  - Else call `client.messages.parse()` (model `claude-sonnet-4-6`) with a PDF
    document block (base64) and a Pydantic schema for the four fields. The prompt
    instructs Claude to return the **earliest** service date when several appear and
    to leave any field it cannot determine null. Money parsed to integer cents.
  - On any SDK/parse error → return `ExtractionResult(configured=True, error=str(e))`
    with all fields null. Never raises to the caller.

**`POST /api/submissions/extract`** (new route in `routes/submissions.py`)
- Accepts a multipart PDF (`file`), same shape as the existing PDF upload.
- Calls `extract_submission_fields` and returns the result as JSON.
- The PDF is **not** stored here; it is re-uploaded on create via the existing
  `POST /api/submissions/{id}/pdf`.

**`models.py` / `schemas.py`**
- `Submission.submitted_date` becomes `nullable=True`.
- `SubmissionCreate.submitted_date` becomes `Optional[date] = None`.
- Response schema exposes `submitted_date: Optional[date]`.

**`alerts.py`**
- `compute_flags` MISSING branch: skip when `submission.submitted_date is None`
  (an unsubmitted claim can't be "missing" from Anthem). When set, behaviour is
  unchanged.

### Frontend

**`utils.ts`** — `computeExpected(billedCents, deductibleRemainingCents, oopRemainingCents, coinsurancePct) -> number` implementing the formula above. Pure, unit-tested.

**`api.ts`** — `api.submissions.extract(file) -> ExtractionResult`.

**`types.ts`** — `ExtractionResult` interface mirroring the backend.

**`Submissions.tsx` `SubmissionModal`**
- Add an "Extract from PDF" button beside the file input (step-1 only). Disabled
  until a PDF is selected; shows a spinner while extracting.
  - On `{configured:false}` → inline note "PDF auto-fill unavailable" and do nothing else.
  - On `{configured:true, error}` → inline note "Couldn't read the PDF — enter fields manually".
  - On success → prefill only the fields Claude returned; trigger expected recompute.
- Wire expected to `computeExpected`, recomputing whenever billed or network changes,
  using `totals` (benefits per network) + plan config. Stop auto-computing once the
  user edits the expected field by hand (`expectedDirty` flag).
- `submitted_date` is removed from the step-1 form (Edit mode keeps it as an editable
  date so a claim can be confirmed later).
- Two-step state: after a successful create + PDF upload, set `step = 2` instead of
  closing. On entering step 2, `window.open(ANTHEM_URL, "_blank")`.
- Step 2 panel: "Submission saved locally." + buttons:
  - "I've submitted to Anthem" → `PATCH /api/submissions/{id}` with `submitted_date = today` → close.
  - "Do it later" → close (leaves `submitted_date` null).

**`api.ts` plan config** — already added (`api.planConfig.get`).

## Data flow

```
Add Submission modal (step 1)
  → (optional) select PDF → "Extract from PDF"
      → POST /api/submissions/extract
      → configured:false → manual note; else prefill returned fields
      → expected auto-computes from billed + network + plan config + benefits
  → user reviews / edits fields
  → "Add Submission"
      → POST /api/submissions     (submitted_date = null)
      → POST /api/submissions/{id}/pdf   (if a PDF was attached)
      → window.open(ANTHEM_URL, "_blank")
      → modal → step 2
  → step 2:
      "I've submitted to Anthem" → PATCH submitted_date = today → close
      "Do it later"             → close (submitted_date stays null)
```

## Error handling

| Condition | Behaviour |
|---|---|
| No `ANTHROPIC_API_KEY` | `extract` returns `{configured:false}`; UI shows "PDF auto-fill unavailable"; manual entry; PDF still attachable |
| Claude error/timeout | `extract` returns `{configured:true, error}`; UI shows "Couldn't read the PDF — enter fields manually"; form untouched |
| Partial extraction | Only found fields prefilled; rest blank |
| Missing benefits snapshot for network | Expected left blank; user enters manually |
| Create succeeds, PDF upload fails | Surface the error; record already created (existing behaviour) |

The app runs over plain HTTP on localhost; the extract endpoint carries a PDF (no
credentials), consistent with the existing CSV-upload surface. The API key never
traverses the web layer — it is read from the backend environment by the SDK.

## Testing

- **Backend `extraction.py`**: with the Claude call mocked — success maps fields +
  parses money to cents and picks earliest date; SDK error → `configured:true, error`;
  no env key → `configured:false`. No live API calls in tests.
- **Backend endpoint**: `POST /api/submissions/extract` returns `{configured:false}`
  when the key is absent (the default in CI).
- **Backend alerts**: MISSING is suppressed when `submitted_date is None`; still fires
  when set and older than threshold.
- **Backend regression**: existing suite green with nullable `submitted_date`
  (update the dashboard-empty / submission-create fixtures as needed).
- **Frontend `computeExpected`**: deductible-only, coinsurance, and OOP-cap cases.

## Out of scope (YAGNI)

- Auto-detecting the network from the PDF (user-selected; Claude can't reliably tell
  in-network-exception from OON).
- Claude-extracting the expected amount (it is computed).
- Storing the Anthropic key in Keychain (env var chosen; could mirror the Anthem
  Keychain pattern later if desired).
- Any "Anthem-confirmed" badge / separate status column (the nullable `submitted_date`
  is the single source of truth).
