# PDF-Prefilled Submission Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user upload a claim PDF that Claude reads to prefill the submission form (with expected reimbursement computed locally), fall back to manual entry when no API key is set, and drive a two-step Add-Submission flow that opens Anthem's questionnaire and tracks whether the claim was actually submitted.

**Architecture:** PDF→field extraction runs in the FastAPI backend (Python `anthropic` SDK, keeps the API key off the browser); expected reimbursement is computed in the React modal from the benefits snapshot + plan-config coinsurance. `submitted_date` becomes nullable and is the single "submitted to Anthem" marker; a null value surfaces a new info-level `UNSUBMITTED` alert.

**Tech Stack:** FastAPI + SQLAlchemy 2.x + SQLite (backend), `anthropic` Python SDK, React 19 + TypeScript + Vite + TanStack Query (frontend), pytest (backend tests), vitest (new, frontend unit tests).

## Global Constraints

- All money is integer cents — never floats. Reuse `app.ingest._parse_money` (`"$570.00"` → `57000`) and `app.ingest._parse_date` (ISO + `"May 6, 2026"`).
- Extraction model: `claude-sonnet-4-6`.
- Anthropic API key: read from env `ANTHROPIC_API_KEY` via the SDK default client. Never logged, never sent through the web layer.
- Anthem questionnaire URL: `https://membersecure.anthem.com/member/claims/submission-questionnaire`.
- Expected reimbursement formula (cents): `deductible_applied = min(billed, deductible_remaining)`; `after_deductible = billed - deductible_applied`; `member_oop = min(deductible_applied + round(after_deductible * coinsurance_pct), oop_remaining)`; `expected = billed - member_oop`.
- Network selects inputs: `out_of_network` → OON benefits + `out_of_network_coinsurance_pct`; `in_network_exception` → in-network benefits + `in_network_coinsurance_pct`.
- Run backend tests from `backend/` with the venv active (`source .venv/bin/activate`). Run frontend commands from `frontend/`.

---

### Task 1: Make `submitted_date` nullable end-to-end

**Files:**
- Modify: `backend/app/models.py:29`
- Modify: `backend/app/schemas.py:16` and `backend/app/schemas.py:47`
- Modify: `frontend/src/types.ts:15` and `frontend/src/types.ts:34`
- Test: `backend/tests/test_submissions.py`

**Interfaces:**
- Produces: `Submission.submitted_date` is `Optional[date]`; `SubmissionCreate.submitted_date: Optional[date] = None`; `SubmissionResponse.submitted_date: Optional[date]`; TS `SubmissionResponse.submitted_date: string | null` and `SubmissionCreate.submitted_date?: string`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_submissions.py`:

```python
def test_create_submission_without_submitted_date(client):
    resp = client.post("/api/submissions", json={
        "member_name": "James OLeary",
        "provider_name": "Joyful Behavior Therapy",
        "service_date": "2026-05-06",
        "amount_billed": 57000,
        "expected_reimbursement": 25900,
        "network_treatment": "out_of_network",
        "submission_method": "portal",
    })
    assert resp.status_code == 201
    assert resp.json()["submitted_date"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_submissions.py::test_create_submission_without_submitted_date -v`
Expected: FAIL (422 — `submitted_date` currently required).

- [ ] **Step 3: Make the column and schemas nullable**

In `backend/app/models.py`, change line 29 from:

```python
    submitted_date: Mapped[date] = mapped_column(Date, nullable=False)
```

to:

```python
    submitted_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
```

In `backend/app/schemas.py`, change `SubmissionCreate` line 16 from `submitted_date: date` to:

```python
    submitted_date: Optional[date] = None
```

and `SubmissionResponse` line 47 from `submitted_date: date` to:

```python
    submitted_date: Optional[date]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_submissions.py -v`
Expected: PASS (all submission tests green).

- [ ] **Step 5: Update the frontend types**

In `frontend/src/types.ts`, change `SubmissionResponse` line 15 to `submitted_date: string | null` and `SubmissionCreate` line 34 to `submitted_date?: string`.

- [ ] **Step 6: Verify the frontend still type-checks**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/schemas.py backend/tests/test_submissions.py frontend/src/types.ts
git commit -m "feat: make submission submitted_date nullable"
```

---

### Task 2: UNSUBMITTED alert + MISSING null-guard

**Files:**
- Modify: `backend/app/alerts.py:31-38`
- Test: `backend/tests/test_alerts.py`

**Interfaces:**
- Consumes: `Submission.submitted_date: Optional[date]` (Task 1).
- Produces: `compute_flags` emits `Alert("UNSUBMITTED", "info", {})` when `match is None and submitted_date is None`; MISSING only when `submitted_date is not None`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_alerts.py` inside `class TestComputeFlags`:

```python
    def test_unsubmitted_flag_when_no_submitted_date(self):
        sub = _make_submission()
        sub.submitted_date = None  # bypass the helper's `or default`
        flags = compute_flags(sub, match=None)
        assert len(flags) == 1
        assert flags[0].flag == "UNSUBMITTED"
        assert flags[0].severity == "info"

    def test_no_missing_when_unsubmitted(self):
        sub = _make_submission()
        sub.submitted_date = None
        flags = compute_flags(sub, match=None)
        assert not any(f.flag == "MISSING" for f in flags)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_alerts.py -k "unsubmitted or no_missing_when" -v`
Expected: FAIL (no UNSUBMITTED flag yet; current code does `(today - None).days` → TypeError).

- [ ] **Step 3: Implement the branch**

In `backend/app/alerts.py`, replace the unmatched branch (currently lines 31-38):

```python
    if match is None:
        days = (today - submission.submitted_date).days
        if days > config.MISSING_DAYS:
            alerts.append(Alert("MISSING", "red", {
                "submitted_date": str(submission.submitted_date),
                "days_waiting": days,
            }))
        return alerts
```

with:

```python
    if match is None:
        if submission.submitted_date is None:
            alerts.append(Alert("UNSUBMITTED", "info", {}))
            return alerts
        days = (today - submission.submitted_date).days
        if days > config.MISSING_DAYS:
            alerts.append(Alert("MISSING", "red", {
                "submitted_date": str(submission.submitted_date),
                "days_waiting": days,
            }))
        return alerts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_alerts.py -v`
Expected: PASS (all alert tests green).

- [ ] **Step 5: Commit**

```bash
git add backend/app/alerts.py backend/tests/test_alerts.py
git commit -m "feat: add UNSUBMITTED info flag for claims with no submitted_date"
```

---

### Task 3: Dashboard `unsubmitted` count

**Files:**
- Modify: `backend/app/schemas.py` (`DashboardCounts`)
- Modify: `backend/app/routes/dashboard.py:42-51`
- Test: `backend/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `UNSUBMITTED` flag (Task 2).
- Produces: `DashboardCounts.unsubmitted: int = 0`, incremented in the dashboard loop.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_dashboard.py`:

```python
def test_dashboard_unsubmitted_count(client, make_submission):
    make_submission(submitted_date=None, service_date=date(2026, 5, 6))
    resp = client.get("/api/dashboard?year=2026")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"]["unsubmitted"] == 1
    assert any(a["flag"] == "UNSUBMITTED" for a in data["alerts"])
```

Ensure `from datetime import date` is imported at the top of the test file (add if missing).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_dashboard.py::test_dashboard_unsubmitted_count -v`
Expected: FAIL (`KeyError: 'unsubmitted'`).

- [ ] **Step 3: Add the count field and increment**

In `backend/app/schemas.py`, add `unsubmitted` to `DashboardCounts`:

```python
class DashboardCounts(BaseModel):
    missing: int = 0
    stale_pending: int = 0
    denied: int = 0
    underpaid: int = 0
    overpaid: int = 0
    unsubmitted: int = 0
    vanished: int = 0
```

In `backend/app/routes/dashboard.py`, add a branch in the count loop (after the `VANISHED` branch, lines 50-51):

```python
            elif flag.flag == "VANISHED":
                counts.vanished += 1
            elif flag.flag == "UNSUBMITTED":
                counts.unsubmitted += 1
```

- [ ] **Step 4: Fix the existing empty-dashboard assertion**

In `backend/tests/test_dashboard.py`, update `test_dashboard_empty`'s expected counts dict to include `"unsubmitted": 0`:

```python
    assert data["counts"] == {"missing": 0, "stale_pending": 0, "denied": 0, "underpaid": 0, "overpaid": 0, "unsubmitted": 0, "vanished": 0}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_dashboard.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/dashboard.py backend/tests/test_dashboard.py
git commit -m "feat: count UNSUBMITTED claims in dashboard"
```

---

### Task 4: Surface UNSUBMITTED on the frontend dashboard

**Files:**
- Modify: `frontend/src/types.ts` (`DashboardCounts`)
- Modify: `frontend/src/utils.ts` (`FLAG_LABELS`)
- Modify: `frontend/src/pages/Dashboard.tsx:21-28`

**Interfaces:**
- Consumes: backend `counts.unsubmitted` (Task 3).
- Produces: an "Unsubmitted" dashboard card filtering on flag `UNSUBMITTED`.

- [ ] **Step 1: Add the count field to the type**

In `frontend/src/types.ts`, in `DashboardCounts`, add `unsubmitted: number` (next to `overpaid`).

- [ ] **Step 2: Add the flag label**

In `frontend/src/utils.ts`, in `FLAG_LABELS`, add:

```ts
  UNSUBMITTED: 'Unsubmitted',
```

- [ ] **Step 3: Add the dashboard card**

In `frontend/src/pages/Dashboard.tsx`, add to the `countItems` array (after the `OVERPAID` entry):

```tsx
    { flag: 'UNSUBMITTED', label: 'Unsubmitted', count: counts.unsubmitted, color: 'bg-blue-100 text-blue-700 border-blue-200' },
```

- [ ] **Step 4: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/utils.ts frontend/src/pages/Dashboard.tsx
git commit -m "feat: show Unsubmitted count card on dashboard"
```

---

### Task 5: Anthropic extraction module

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/extraction.py`
- Modify: `backend/app/schemas.py` (add `ExtractionResult`)
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Produces: `app.schemas.ExtractionResult` (BaseModel: `configured: bool`, `error: Optional[str] = None`, `member_name: Optional[str] = None`, `provider_name: Optional[str] = None`, `first_service_date: Optional[date] = None`, `amount_billed_cents: Optional[int] = None`) and `app.extraction.extract_submission_fields(pdf_bytes: bytes) -> ExtractionResult`.

- [ ] **Step 1: Add the dependency and install it**

In `backend/requirements.txt`, add a line:

```
anthropic>=0.69.0
```

Run: `cd backend && source .venv/bin/activate && pip install -r requirements.txt`
Expected: `anthropic` installs.

- [ ] **Step 2: Add the `ExtractionResult` schema**

In `backend/app/schemas.py`, after the `SubmissionResponse` class, add:

```python
class ExtractionResult(BaseModel):
    configured: bool
    error: Optional[str] = None
    member_name: Optional[str] = None
    provider_name: Optional[str] = None
    first_service_date: Optional[date] = None
    amount_billed_cents: Optional[int] = None
```

- [ ] **Step 3: Write the failing tests**

Create `backend/tests/test_extraction.py`:

```python
import json
from datetime import date
from unittest.mock import MagicMock

from app import extraction


def _fake_client(payload: dict):
    msg = MagicMock()
    msg.content = [MagicMock(type="text", text=json.dumps(payload))]
    client = MagicMock()
    client.messages.create.return_value = msg
    return client


def test_not_configured_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is False


def test_success_maps_fields(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = _fake_client({
        "member_name": "Nolan OLeary",
        "provider_name": "Citrus Speech",
        "first_service_date": "2026-05-06",
        "amount_billed": "$570.00",
    })
    monkeypatch.setattr(extraction.anthropic, "Anthropic", lambda *a, **k: client)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert result.error is None
    assert result.member_name == "Nolan OLeary"
    assert result.provider_name == "Citrus Speech"
    assert result.first_service_date == date(2026, 5, 6)
    assert result.amount_billed_cents == 57000


def test_blank_fields_become_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = _fake_client({
        "member_name": "",
        "provider_name": "",
        "first_service_date": "",
        "amount_billed": "",
    })
    monkeypatch.setattr(extraction.anthropic, "Anthropic", lambda *a, **k: client)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert result.member_name is None
    assert result.amount_billed_cents is None
    assert result.first_service_date is None


def test_api_error_is_captured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    monkeypatch.setattr(extraction.anthropic, "Anthropic", lambda *a, **k: client)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert "boom" in result.error
    assert result.member_name is None
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_extraction.py -v`
Expected: FAIL (`app.extraction` does not exist).

- [ ] **Step 5: Implement the module**

Create `backend/app/extraction.py`:

```python
import base64
import json
import os
from typing import Optional

import anthropic

from app.ingest import _parse_date, _parse_money
from app.schemas import ExtractionResult

_MODEL = "claude-sonnet-4-6"

_SCHEMA = {
    "type": "object",
    "properties": {
        "member_name": {"type": "string", "description": "Patient or member full name; empty string if not found"},
        "provider_name": {"type": "string", "description": "Provider, practice, or facility name; empty string if not found"},
        "first_service_date": {"type": "string", "description": "Earliest date of service if several appear, ISO YYYY-MM-DD preferred; empty string if not found"},
        "amount_billed": {"type": "string", "description": "Total amount billed including the dollar sign, e.g. \"$570.00\"; empty string if not found"},
    },
    "required": ["member_name", "provider_name", "first_service_date", "amount_billed"],
    "additionalProperties": False,
}

_PROMPT = (
    "This is a medical claim or superbill PDF. Extract the member name, the provider "
    "name, the earliest date of service (if several are listed), and the total amount "
    "billed, and return them in the required JSON format. If a field cannot be "
    "determined, use an empty string."
)


def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    return s or None


def extract_submission_fields(pdf_bytes: bytes) -> ExtractionResult:
    """Send a claim PDF to Claude and extract submission fields.

    Returns configured=False when no ANTHROPIC_API_KEY is set, and
    configured=True with an error string when the call or parse fails. Never
    raises — callers fall back to manual entry.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ExtractionResult(configured=False)

    try:
        client = anthropic.Anthropic()
        b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        message = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        )
        text = next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001 — degrade gracefully to manual entry
        return ExtractionResult(configured=True, error=str(e))

    billed_raw = _clean(data.get("amount_billed"))
    date_raw = _clean(data.get("first_service_date"))
    try:
        service_date = _parse_date(date_raw) if date_raw else None
    except ValueError:
        service_date = None

    return ExtractionResult(
        configured=True,
        member_name=_clean(data.get("member_name")),
        provider_name=_clean(data.get("provider_name")),
        first_service_date=service_date,
        amount_billed_cents=_parse_money(billed_raw) if billed_raw else None,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_extraction.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/extraction.py backend/app/schemas.py backend/tests/test_extraction.py
git commit -m "feat: add Claude PDF extraction module"
```

---

### Task 6: `POST /api/submissions/extract` endpoint

**Files:**
- Modify: `backend/app/routes/submissions.py`
- Test: `backend/tests/test_submissions.py`

**Interfaces:**
- Consumes: `extract_submission_fields` and `ExtractionResult` (Task 5).
- Produces: `POST /api/submissions/extract` (multipart `file`) → `ExtractionResult` JSON.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_submissions.py`:

```python
def test_extract_returns_not_configured_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/submissions/extract",
        files={"file": ("claim.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_submissions.py::test_extract_returns_not_configured_without_key -v`
Expected: FAIL (404 — route not defined).

- [ ] **Step 3: Add the route**

In `backend/app/routes/submissions.py`, add the import near the top (after the existing `from app.schemas import ...` line):

```python
from app.extraction import extract_submission_fields
from app.schemas import ExtractionResult
```

Then add the route (place it just above the existing `upload_pdf` route):

```python
@router.post("/submissions/extract", response_model=ExtractionResult)
async def extract_submission(file: UploadFile):
    data = await file.read()
    return extract_submission_fields(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_submissions.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && source .venv/bin/activate && pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/submissions.py backend/tests/test_submissions.py
git commit -m "feat: add /submissions/extract endpoint"
```

---

### Task 7: `computeExpected` helper + vitest

**Files:**
- Modify: `frontend/package.json` (devDependency + `test` script)
- Create: `frontend/vitest.config.ts`
- Modify: `frontend/src/utils.ts`
- Test: `frontend/src/utils.test.ts`

**Interfaces:**
- Produces: `computeExpected(billedCents, deductibleRemainingCents, oopRemainingCents, coinsurancePct) => number`.

- [ ] **Step 1: Install vitest and add the test script**

Run: `cd frontend && npm install -D vitest`

In `frontend/package.json`, add to `scripts`:

```json
    "test": "vitest run",
```

Create `frontend/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: { environment: 'node' },
})
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/utils.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { computeExpected } from './utils'

describe('computeExpected', () => {
  it('routes the whole bill to the deductible when deductible remaining covers it', () => {
    expect(computeExpected(100000, 200000, 9999999, 0.3)).toBe(0)
  })

  it('applies deductible then coinsurance', () => {
    // $570 billed, $200 deductible remaining, 30% coinsurance → $259 expected
    expect(computeExpected(57000, 20000, 9999999, 0.3)).toBe(25900)
  })

  it('caps member cost at the out-of-pocket remaining', () => {
    // member would owe $311 but only $50 OOP remains → plan pays the rest
    expect(computeExpected(57000, 20000, 5000, 0.3)).toBe(52000)
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL (`computeExpected` is not exported).

- [ ] **Step 4: Implement the helper**

In `frontend/src/utils.ts`, add:

```ts
export function computeExpected(
  billedCents: number,
  deductibleRemainingCents: number,
  oopRemainingCents: number,
  coinsurancePct: number,
): number {
  const deductibleApplied = Math.min(billedCents, Math.max(0, deductibleRemainingCents))
  const afterDeductible = billedCents - deductibleApplied
  const memberOop = Math.min(
    deductibleApplied + Math.round(afterDeductible * coinsurancePct),
    Math.max(0, oopRemainingCents),
  )
  return billedCents - memberOop
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/utils.ts frontend/src/utils.test.ts
git commit -m "feat: add computeExpected helper with vitest"
```

---

### Task 8: Modal — Extract-from-PDF prefill + live expected compute

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/types.ts` (add `ExtractionResult`)
- Modify: `frontend/src/pages/Submissions.tsx` (`SubmissionModal`)

**Interfaces:**
- Consumes: `POST /api/submissions/extract` (Task 6), `computeExpected` (Task 7), `api.planConfig.get` (existing), `api.totals.get` (existing).
- Produces: `api.submissions.extract(file: File) => Promise<ExtractionResult>`, TS `ExtractionResult` interface.

- [ ] **Step 1: Add the API client method and type**

In `frontend/src/types.ts`, add:

```ts
export interface ExtractionResult {
  configured: boolean
  error: string | null
  member_name: string | null
  provider_name: string | null
  first_service_date: string | null
  amount_billed_cents: number | null
}
```

In `frontend/src/api.ts`, import `ExtractionResult` in the type import block, then add to the `submissions` object (after `uploadPdf`):

```ts
    extract: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return req<ExtractionResult>('/submissions/extract', { method: 'POST', body: fd })
    },
```

- [ ] **Step 2: Load plan config in the modal and add extraction/compute state**

In `frontend/src/pages/Submissions.tsx`, add the imports:

```tsx
import { useEffect } from 'react'
import { computeExpected } from '../utils'
import type { ExtractionResult } from '../types'
```

(Merge `useEffect` into the existing `react` import; merge `ExtractionResult` into the existing `../types` import.)

Inside `SubmissionModal`, after the existing `totals` query, add:

```tsx
  const { data: planConfig } = useQuery({ queryKey: ['planConfig'], queryFn: api.planConfig.get })
  const [extracting, setExtracting] = useState(false)
  const [extractNote, setExtractNote] = useState<string | null>(null)
  const [expectedDirty, setExpectedDirty] = useState(false)
```

- [ ] **Step 3: Wire live expected computation**

In `SubmissionModal`, after the state declarations, add:

```tsx
  useEffect(() => {
    if (isEdit || expectedDirty || !totals || !planConfig) return
    const billed = Math.round((parseFloat(form.amount_billed) || 0) * 100)
    if (!billed) return
    const oon = form.network_treatment === 'out_of_network'
    const benefits = oon ? totals.out_of_network.benefits : totals.in_network.benefits
    if (!benefits) return
    const dedRemaining = benefits.deductible_limit - benefits.deductible_spent
    const oopRemaining = benefits.oop_limit - benefits.oop_spent
    const pct = (oon ? planConfig.out_of_network_coinsurance_pct : planConfig.in_network_coinsurance_pct) / 100
    const expected = computeExpected(billed, dedRemaining, oopRemaining, pct)
    setForm((p) => ({ ...p, expected_reimbursement: (expected / 100).toFixed(2) }))
  }, [form.amount_billed, form.network_treatment, totals, planConfig, isEdit, expectedDirty])
```

Mark the expected field dirty when the user edits it: change its `onChange` (the existing `expected_reimbursement` input, around line 121) to:

```tsx
              onChange={(e) => { setExpectedDirty(true); setForm((p) => ({ ...p, expected_reimbursement: e.target.value })) }}
```

- [ ] **Step 4: Add the Extract-from-PDF button**

In `SubmissionModal`, replace the existing PDF file-input block (the `{!isEdit && (...)}` around lines 143-148) with:

```tsx
        {!isEdit && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">PDF (optional)</label>
            <div className="flex items-center gap-3">
              <input type="file" accept=".pdf" onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)} className="text-sm" />
              <button
                type="button"
                disabled={!pdfFile || extracting}
                onClick={async () => {
                  if (!pdfFile) return
                  setExtracting(true)
                  setExtractNote(null)
                  try {
                    const r: ExtractionResult = await api.submissions.extract(pdfFile)
                    if (!r.configured) { setExtractNote('PDF auto-fill unavailable (no API key configured).'); return }
                    if (r.error) { setExtractNote('Couldn’t read the PDF — please enter fields manually.'); return }
                    setForm((p) => ({
                      ...p,
                      member_name: r.member_name ?? p.member_name,
                      provider_name: r.provider_name ?? p.provider_name,
                      service_date: r.first_service_date ?? p.service_date,
                      amount_billed: r.amount_billed_cents != null ? String(r.amount_billed_cents / 100) : p.amount_billed,
                    }))
                  } catch {
                    setExtractNote('Couldn’t read the PDF — please enter fields manually.')
                  } finally {
                    setExtracting(false)
                  }
                }}
                className="px-3 py-1 text-sm border rounded text-blue-700 border-blue-300 hover:bg-blue-50 disabled:opacity-50">
                {extracting ? 'Reading…' : 'Extract from PDF'}
              </button>
            </div>
            {extractNote && <div className="text-xs text-amber-700 mt-1">{extractNote}</div>}
          </div>
        )}
```

- [ ] **Step 5: Remove `submitted_date` from the create form, keep it for edit**

In `SubmissionModal`, the date grid currently renders both `service_date` and `submitted_date` (around lines 92-104). Replace that grid with one that always shows `service_date` and shows `submitted_date` only when editing:

```tsx
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Service Date</label>
            <input type="date" value={form.service_date} onChange={set('service_date')}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          {isEdit && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Submitted Date</label>
              <input type="date" value={form.submitted_date} onChange={set('submitted_date')}
                className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          )}
        </div>
```

In the create branch of the mutation (the `else` block around lines 58-63), build the body explicitly without `submitted_date`:

```tsx
      } else {
        const body: SubmissionCreate = {
          member_name: form.member_name,
          provider_name: form.provider_name,
          service_date: form.service_date,
          network_treatment: form.network_treatment,
          submission_method: form.submission_method,
          notes: form.notes,
          ...dollars,
        }
        const sub = await api.submissions.create(body)
        if (pdfFile) await api.submissions.uploadPdf(sub.id, pdfFile)
        return sub
      }
```

- [ ] **Step 6: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 7: Manual verification**

Start backend (`cd backend && source .venv/bin/activate && uvicorn app.main:app --reload`) and frontend (`cd frontend && npm run dev`). Open Add Submission:
- Type a Billed amount and toggle Network → Expected updates automatically; editing Expected stops the auto-update.
- With no `ANTHROPIC_API_KEY` set, pick a PDF and click "Extract from PDF" → "PDF auto-fill unavailable" note; form untouched.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api.ts frontend/src/types.ts frontend/src/pages/Submissions.tsx
git commit -m "feat: PDF extract prefill and live expected computation in submission modal"
```

---

### Task 9: Modal — two-step Anthem confirmation flow

**Files:**
- Modify: `frontend/src/pages/Submissions.tsx` (`SubmissionModal`)

**Interfaces:**
- Consumes: `api.submissions.create`, `api.submissions.update`, `api.submissions.uploadPdf` (existing).
- Produces: after create, the modal opens the Anthem URL and shows a confirm/later step that PATCHes `submitted_date`.

- [ ] **Step 1: Add step state and the Anthem URL constant**

Near the top of `frontend/src/pages/Submissions.tsx` (module scope, below imports), add:

```tsx
const ANTHEM_URL = 'https://membersecure.anthem.com/member/claims/submission-questionnaire'
```

Inside `SubmissionModal`, add state and capture the created submission id:

```tsx
  const [step, setStep] = useState<1 | 2>(1)
  const [createdId, setCreatedId] = useState<string | null>(null)
```

- [ ] **Step 2: On successful create, advance to step 2 instead of closing**

Change the mutation's `onSuccess` so a *create* (not edit) opens Anthem and advances to step 2, while edit keeps closing:

```tsx
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      if (isEdit) { onClose(); return }
      setCreatedId(result.id)
      window.open(ANTHEM_URL, '_blank')
      setStep(2)
    },
```

- [ ] **Step 3: Add a confirm mutation**

In `SubmissionModal`, add:

```tsx
  const confirmMutation = useMutation({
    mutationFn: () => api.submissions.update(createdId!, { submitted_date: new Date().toISOString().slice(0, 10) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onClose()
    },
  })
```

- [ ] **Step 4: Render step 2**

Wrap the existing modal body so step 2 shows the confirmation panel. Immediately after `<Modal ...>` opens, branch on `step`. Replace the opening of the body (the `<div className="space-y-3">` right after `<Modal ...>`) so that when `step === 2` a different panel renders:

```tsx
  if (step === 2) {
    return (
      <Modal title="Submit to Anthem" onClose={onClose}>
        <div className="space-y-4">
          <div className="text-sm text-green-700">✓ Submission saved locally.</div>
          <p className="text-sm text-gray-600">
            Anthem’s claim questionnaire was opened in a new tab. Once you’ve submitted the
            claim there, confirm it below.
          </p>
          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Do it later</button>
            <button onClick={() => confirmMutation.mutate()} disabled={confirmMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {confirmMutation.isPending ? 'Saving…' : 'I’ve submitted to Anthem'}
            </button>
          </div>
        </div>
      </Modal>
    )
  }
```

Place this `if (step === 2)` block immediately before the existing `return (` that renders the form.

- [ ] **Step 5: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 6: Manual verification**

With backend + frontend running: Add Submission → fill fields → "Add Submission" → a new tab opens to the Anthem URL and the modal shows the confirm panel.
- "Do it later" → modal closes; the new claim shows the blue **Unsubmitted** badge on the dashboard and submissions list.
- Re-add another, click "I’ve submitted to Anthem" → modal closes; that claim has no Unsubmitted badge (submitted_date set to today).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Submissions.tsx
git commit -m "feat: two-step submission flow opening Anthem and confirming upload"
```

---

### Task 10: Deployment + docs for the API key

**Files:**
- Modify: `deploy/README.md`
- Modify: `CLAUDE.md`
- Modify: `deploy/com.claimstracker.server.plist` template (if it defines `EnvironmentVariables`; otherwise document the addition)

**Interfaces:**
- Produces: documented way to provide `ANTHROPIC_API_KEY` to the running service.

- [ ] **Step 1: Inspect the server LaunchAgent template**

Run: `sed -n '1,80p' deploy/com.claimstracker.server.plist`
Note whether an `<key>EnvironmentVariables</key>` dict exists.

- [ ] **Step 2: Document the key in the deploy runbook**

In `deploy/README.md`, add a short subsection under the server/refresh setup explaining that PDF auto-fill requires `ANTHROPIC_API_KEY` in the server process environment, e.g. by adding to the server plist's `EnvironmentVariables` dict:

```xml
    <key>EnvironmentVariables</key>
    <dict>
      <key>ANTHROPIC_API_KEY</key>
      <string>sk-ant-...</string>
    </dict>
```

and reloading the agent (`launchctl kickstart -k gui/$(id -u)/com.claimstracker.server`). Note that without the key, PDF auto-fill is simply unavailable and submissions are entered manually.

- [ ] **Step 3: Note the feature in CLAUDE.md**

In `CLAUDE.md`, under the backend architecture section, add a one-line bullet:

> - **`extraction.py`** — sends an uploaded claim PDF to Claude (`claude-sonnet-4-6`, key from `ANTHROPIC_API_KEY`) to prefill member/provider/first-service-date/billed. Returns `configured=False` when no key is set so the UI falls back to manual entry. Expected reimbursement is computed client-side, not extracted.

Also add a note that `submitted_date` is nullable and is set when the user confirms the claim was uploaded to Anthem (two-step Add Submission modal), with the `UNSUBMITTED` info flag surfacing claims that have no `submitted_date`.

- [ ] **Step 4: Commit**

```bash
git add deploy/README.md CLAUDE.md
git commit -m "docs: document ANTHROPIC_API_KEY and PDF-prefill submission flow"
```

---

## Final verification

- [ ] **Backend suite green**

Run: `cd backend && source .venv/bin/activate && pytest -q`
Expected: all tests pass.

- [ ] **Frontend unit tests + build green**

Run: `cd frontend && npm test && npm run build`
Expected: vitest passes; build succeeds.
