# Anthropic API Key in Keychain + Settings Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the Anthropic API key in the macOS Keychain (set via a terminal script), have PDF extraction resolve it from the Keychain with an env-var fallback, and show a read-only configured/not-configured status in Settings — without the key ever crossing the web layer.

**Architecture:** Reuse the existing `keyring`-based `credentials.py` pattern (as used for Anthem creds) under a new service `claims-tracker-anthropic`. Extraction resolves the key Keychain→env. A new read-only `GET /api/settings/anthropic-key` exposes only a boolean. The Settings page renders a status card. The key is set with `deploy/store_credentials.py --anthropic`.

**Tech Stack:** FastAPI + SQLAlchemy/SQLite, `keyring`, `anthropic` SDK (backend); React 19 + TS + Vite + TanStack Query (frontend); pytest.

## Global Constraints

- The API key is NEVER accepted or returned over HTTP — only a boolean `configured` is exposed. No POST/PUT for the key.
- Keychain service for the Anthropic key is exactly `claims-tracker-anthropic`; key name `api_key`. (The Anthem service `claims-tracker-anthem` is unchanged.)
- Extraction resolves the key as `credentials.get_anthropic_key() or os.environ.get("ANTHROPIC_API_KEY")`; when neither is set it returns `configured=False` and never raises.
- Tests must never touch the real system Keychain: unit-test `credentials` with the fake-keyring pattern already in `test_credentials.py`; in extraction/settings tests stub `get_anthropic_key` directly.
- Backend tests run from the repo root via `backend/.venv/bin/pytest backend/tests/...` (no `source`). Frontend build/test: `npm run build --prefix frontend`, `npm test --prefix frontend`.

---

### Task 1: Keychain helpers for the Anthropic key

**Files:**
- Modify: `backend/app/credentials.py`
- Test: `backend/tests/test_credentials.py`

**Interfaces:**
- Produces: `app.credentials.ANTHROPIC_SERVICE = "claims-tracker-anthropic"`; `store_anthropic_key(key: str) -> None`; `get_anthropic_key() -> str | None` (returns `None` when unset or empty).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_credentials.py`:

```python
def test_anthropic_key_roundtrip(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _FakeKeyring())
    creds.store_anthropic_key("sk-ant-abc123")
    assert creds.get_anthropic_key() == "sk-ant-abc123"


def test_anthropic_key_none_when_unset(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _FakeKeyring())
    assert creds.get_anthropic_key() is None


def test_anthropic_key_none_when_empty(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(creds, "keyring", fake)
    fake.set_password(creds.ANTHROPIC_SERVICE, "api_key", "")
    assert creds.get_anthropic_key() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/bin/pytest backend/tests/test_credentials.py -k anthropic -v`
Expected: FAIL (`AttributeError: module 'app.credentials' has no attribute 'store_anthropic_key'`).

- [ ] **Step 3: Implement the helpers**

In `backend/app/credentials.py`, after the existing Anthem helpers, add:

```python
ANTHROPIC_SERVICE = "claims-tracker-anthropic"
_ANTHROPIC_KEY = "api_key"


def store_anthropic_key(key: str) -> None:
    keyring.set_password(ANTHROPIC_SERVICE, _ANTHROPIC_KEY, key)


def get_anthropic_key() -> str | None:
    key = keyring.get_password(ANTHROPIC_SERVICE, _ANTHROPIC_KEY)
    return key or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend/.venv/bin/pytest backend/tests/test_credentials.py -v`
Expected: PASS (all credentials tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/credentials.py backend/tests/test_credentials.py
git commit -m "feat: store/get Anthropic API key in the Keychain"
```

---

### Task 2: Extraction resolves the key Keychain→env

**Files:**
- Modify: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `app.credentials.get_anthropic_key` (Task 1).
- Produces: `extract_submission_fields` resolves `credentials.get_anthropic_key() or os.environ.get("ANTHROPIC_API_KEY")` and constructs `anthropic.Anthropic(api_key=key)`.

- [ ] **Step 1: Update existing tests to stub the Keychain, and add resolution tests**

In `backend/tests/test_extraction.py`, the existing success/blank/api-error tests set `ANTHROPIC_API_KEY` and must now also stub the Keychain to `None` so they exercise the env path deterministically. Add this line immediately after each `monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")` in `test_success_maps_fields`, `test_blank_fields_become_none`, `test_api_error_is_captured`, and `test_malformed_values_degrade_to_none`:

```python
    monkeypatch.setattr(extraction.credentials, "get_anthropic_key", lambda: None)
```

Then update `test_not_configured_without_api_key` to also clear the Keychain, and add two new tests. Replace `test_not_configured_without_api_key` with:

```python
def test_not_configured_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(extraction.credentials, "get_anthropic_key", lambda: None)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is False


def test_uses_keychain_key_when_present(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(extraction.credentials, "get_anthropic_key", lambda: "sk-kc-key")
    captured = {}

    def fake_anthropic(*args, **kwargs):
        captured["api_key"] = kwargs.get("api_key")
        msg = MagicMock()
        msg.content = [MagicMock(type="text", text=json.dumps({
            "member_name": "Nolan OLeary", "provider_name": "Citrus Speech",
            "first_service_date": "2026-05-06", "amount_billed": "$570.00",
        }))]
        client = MagicMock()
        client.messages.create.return_value = msg
        return client

    monkeypatch.setattr(extraction.anthropic, "Anthropic", fake_anthropic)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert result.amount_billed_cents == 57000
    assert captured["api_key"] == "sk-kc-key"


def test_falls_back_to_env_when_keychain_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-key")
    monkeypatch.setattr(extraction.credentials, "get_anthropic_key", lambda: None)
    captured = {}

    def fake_anthropic(*args, **kwargs):
        captured["api_key"] = kwargs.get("api_key")
        msg = MagicMock()
        msg.content = [MagicMock(type="text", text=json.dumps({
            "member_name": "", "provider_name": "", "first_service_date": "", "amount_billed": "",
        }))]
        client = MagicMock()
        client.messages.create.return_value = msg
        return client

    monkeypatch.setattr(extraction.anthropic, "Anthropic", fake_anthropic)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert captured["api_key"] == "sk-env-key"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `backend/.venv/bin/pytest backend/tests/test_extraction.py -k "keychain or env_when" -v`
Expected: FAIL (`AttributeError: ... has no attribute 'credentials'` — extraction doesn't import credentials yet; and `api_key` not passed).

- [ ] **Step 3: Implement the resolution change**

In `backend/app/extraction.py`, add the import near the top (after `from app.ingest import _parse_date, _parse_money`):

```python
from app import credentials
```

Replace the env-var check and client construction inside `extract_submission_fields`. Change:

```python
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ExtractionResult(configured=False)

    try:
        client = anthropic.Anthropic()
```

to:

```python
    key = credentials.get_anthropic_key() or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return ExtractionResult(configured=False)

    try:
        client = anthropic.Anthropic(api_key=key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend/.venv/bin/pytest backend/tests/test_extraction.py -v`
Expected: PASS (all extraction tests, including the two new resolution tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: extraction resolves Anthropic key from Keychain then env var"
```

---

### Task 3: Read-only key-status endpoint

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/settings.py`
- Test: `backend/tests/test_settings.py` (create)

**Interfaces:**
- Consumes: `app.credentials.get_anthropic_key` (Task 1).
- Produces: `app.schemas.AnthropicKeyStatus(configured: bool)`; `GET /api/settings/anthropic-key` → `AnthropicKeyStatus`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_settings.py`:

```python
import app.credentials as creds


def test_anthropic_key_status_configured(client, monkeypatch):
    monkeypatch.setattr(creds, "get_anthropic_key", lambda: "sk-ant-xyz")
    resp = client.get("/api/settings/anthropic-key")
    assert resp.status_code == 200
    assert resp.json() == {"configured": True}


def test_anthropic_key_status_not_configured(client, monkeypatch):
    monkeypatch.setattr(creds, "get_anthropic_key", lambda: None)
    resp = client.get("/api/settings/anthropic-key")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/bin/pytest backend/tests/test_settings.py -v`
Expected: FAIL (404 — route not defined).

- [ ] **Step 3: Add the schema and route**

In `backend/app/schemas.py`, after the `ExtractionResult` class, add:

```python
class AnthropicKeyStatus(BaseModel):
    configured: bool
```

In `backend/app/routes/settings.py`, add to the imports at the top:

```python
from app import credentials
from app.schemas import AnthropicKeyStatus
```

(Extend the existing `from app.schemas import ...` line rather than duplicating it if present.) Then add the route (place it after the existing credentials routes, before the plan-config helpers):

```python
@router.get("/settings/anthropic-key", response_model=AnthropicKeyStatus)
def anthropic_key_status():
    return AnthropicKeyStatus(configured=credentials.get_anthropic_key() is not None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `backend/.venv/bin/pytest backend/tests/test_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `backend/.venv/bin/pytest backend/tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/settings.py backend/tests/test_settings.py
git commit -m "feat: add read-only Anthropic key status endpoint"
```

---

### Task 4: `--anthropic` flag on the credential setter script

**Files:**
- Modify: `deploy/store_credentials.py`

**Interfaces:**
- Consumes: `app.credentials.store_anthropic_key` (Task 1).
- Produces: `deploy/store_credentials.py --anthropic` prompts (hidden) and stores the Anthropic key; no flag = existing Anthem flow.

- [ ] **Step 1: Rewrite the script to dispatch on `--anthropic`**

Replace the body of `deploy/store_credentials.py` (keep the module docstring's intent; update it) with:

```python
"""One-time: store credentials in the macOS Keychain.

Anthem (default):
    backend/.venv/bin/python deploy/store_credentials.py
Anthropic API key (PDF auto-fill):
    backend/.venv/bin/python deploy/store_credentials.py --anthropic
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import credentials  # noqa: E402


def _store_anthropic() -> None:
    key = getpass.getpass("Anthropic API key: ").strip()
    if not key:
        print("No key entered; nothing stored.")
        sys.exit(1)
    credentials.store_anthropic_key(key)
    print(f"Stored Anthropic API key in the Keychain (service: {credentials.ANTHROPIC_SERVICE}).")


def _store_anthem() -> None:
    username = input("Anthem email: ").strip()
    password = getpass.getpass("Anthem password: ")
    if not username or not password:
        print("Both fields are required; nothing stored.")
        sys.exit(1)
    credentials.store_credentials(username, password)
    print(f"Stored Anthem credentials in the Keychain (service: {credentials.SERVICE}).")


if __name__ == "__main__":
    if "--anthropic" in sys.argv[1:]:
        _store_anthropic()
    else:
        _store_anthem()
```

- [ ] **Step 2: Verify the script parses**

Run: `backend/.venv/bin/python -c "import ast; ast.parse(open('deploy/store_credentials.py').read()); print('store_credentials.py parses')"`
Expected: prints `store_credentials.py parses`.

- [ ] **Step 3: Self-review**

Confirm: `--anthropic` routes to `_store_anthropic` (calls `credentials.store_anthropic_key`), no-flag routes to `_store_anthem` (unchanged behavior), empty input exits non-zero in both, and the `sys.path` insert + `from app import credentials` still resolve. Do NOT run the script against the real Keychain here (it would write to the login keychain and may prompt).

- [ ] **Step 4: Commit**

```bash
git add deploy/store_credentials.py
git commit -m "feat: add --anthropic flag to store_credentials.py"
```

---

### Task 5: Settings UI status card

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `GET /api/settings/anthropic-key` (Task 3).
- Produces: `api.settings.anthropicKeyStatus()`; an "Anthropic API Key" status card in Settings.

- [ ] **Step 1: Add the type**

In `frontend/src/types.ts`, add:

```ts
export interface AnthropicKeyStatus {
  configured: boolean
}
```

- [ ] **Step 2: Add the API method**

In `frontend/src/api.ts`, add `AnthropicKeyStatus` to the type import block, then add a new group after `planConfig`:

```ts
  settings: {
    anthropicKeyStatus: () => req<AnthropicKeyStatus>('/settings/anthropic-key'),
  },
```

- [ ] **Step 3: Add the status card to Settings**

In `frontend/src/pages/Settings.tsx`, add a query alongside the existing ones in the component:

```tsx
  const { data: anthropicKey } = useQuery({ queryKey: ['anthropicKey'], queryFn: api.settings.anthropicKeyStatus })
```

Then add a card in the rendered output (place it after the Plan Configuration card, before the Alert Thresholds card), matching the existing card styling:

```tsx
      <div className="bg-white border rounded-lg p-6 shadow-sm mb-6">
        <h2 className="font-semibold text-gray-900 mb-1">Anthropic API Key</h2>
        <p className="text-sm text-gray-500 mb-3">Used for PDF auto-fill on new submissions.</p>
        <div className="flex items-center gap-2 text-sm">
          {anthropicKey?.configured ? (
            <span className="text-green-700 font-medium">✓ Configured</span>
          ) : (
            <span className="text-gray-500 font-medium">● Not configured</span>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Set it in the terminal: <code className="bg-gray-100 px-1 rounded">backend/.venv/bin/python deploy/store_credentials.py --anthropic</code>
        </p>
      </div>
```

- [ ] **Step 4: Verify the build**

Run: `npm run build --prefix frontend`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/pages/Settings.tsx
git commit -m "feat: show Anthropic API key status in Settings"
```

---

### Task 6: Update docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `deploy/README.md`

**Interfaces:**
- None (docs only).

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, update the `extraction.py` bullet (added in the prior feature) so it states the key now resolves **Keychain → `ANTHROPIC_API_KEY` env var**, and is set via `deploy/store_credentials.py --anthropic`. In the "Credentials (macOS Keychain)" section, add a sentence noting the Anthropic API key lives under the separate Keychain service `claims-tracker-anthropic` (distinct from the Anthem `claims-tracker-anthem` service), set with the `--anthropic` flag, and that Settings shows its configured status (read-only — the key never crosses the web layer).

- [ ] **Step 2: Update deploy/README.md**

In `deploy/README.md`, change the Anthropic API key subsection (added in the prior feature) so the **primary** instruction is the terminal command:

```
backend/.venv/bin/python deploy/store_credentials.py --anthropic
```

stored in the Keychain (survives reinstalls), and keep the plist `EnvironmentVariables` / `ANTHROPIC_API_KEY` approach described as a fallback. Note that without a key set either way, PDF auto-fill is unavailable and fields are entered manually.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md deploy/README.md
git commit -m "docs: Anthropic key via Keychain (--anthropic) with env-var fallback"
```

---

## Final verification

- [ ] **Backend suite green**

Run: `backend/.venv/bin/pytest backend/tests -q`
Expected: all tests pass.

- [ ] **Frontend build green**

Run: `npm run build --prefix frontend`
Expected: build succeeds.
