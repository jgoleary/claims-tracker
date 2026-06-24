# Anthropic API Key in Keychain + Settings Status — Design

**Date:** 2026-06-24
**Status:** Approved design, pending implementation plan

## Goal

Let the user configure the Anthropic API key (used by PDF auto-fill) without editing
the launchd plist, while honoring this project's stance that secrets stay off the web
layer. The key is stored in the macOS Keychain, set via a terminal script (like the
Anthem credentials), and the Settings page shows only whether it is configured.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Where the key lives | macOS Keychain (new service `claims-tracker-anthropic`) |
| How it is set | Terminal: `deploy/store_credentials.py --anthropic` (hidden input) |
| Web layer | Read-only **status** only (`GET`), never POST the key — secret never crosses HTTP |
| Resolution order in extraction | Keychain first, then `ANTHROPIC_API_KEY` env var (back-compat) |
| Supersedes | Task 10's "put the key in the plist EnvironmentVariables" guidance — env var stays a documented fallback |

## Components

### Backend

**`app/credentials.py`** — add, alongside the existing Anthem helpers:
- `ANTHROPIC_SERVICE = "claims-tracker-anthropic"` and key name `"api_key"`.
- `store_anthropic_key(key: str) -> None` → `keyring.set_password(ANTHROPIC_SERVICE, "api_key", key)`.
- `get_anthropic_key() -> str | None` → returns the stored key, or `None` if unset/empty.

**`app/extraction.py`** — change key resolution in `extract_submission_fields`:
- `key = credentials.get_anthropic_key() or os.environ.get("ANTHROPIC_API_KEY")`.
- If `not key` → `ExtractionResult(configured=False)` (unchanged behavior).
- Else construct the client with the resolved key explicitly: `anthropic.Anthropic(api_key=key)`
  (previously relied on the SDK's default env read; explicit is required so a Keychain-only
  key works). Everything else (never-raises, parsing) is unchanged.
- Add `from app import credentials` import.

**`app/routes/settings.py`** — add a read-only status endpoint:
- `GET /api/settings/anthropic-key` → `AnthropicKeyStatus(configured=bool)` where
  `configured = credentials.get_anthropic_key() is not None`.
- No POST/PUT — the key is never accepted over HTTP.

**`app/schemas.py`** — `class AnthropicKeyStatus(BaseModel): configured: bool`.

### Deploy / CLI

**`deploy/store_credentials.py`** — add argument handling:
- `--anthropic` flag → prompt for the Anthropic API key with `getpass` (hidden), store via
  `credentials.store_anthropic_key`, print confirmation naming the service. Empty input →
  message + non-zero exit, store nothing.
- No flag → existing Anthem username/password flow, unchanged.

### Frontend

**`types.ts`** — `export interface AnthropicKeyStatus { configured: boolean }`.

**`api.ts`** — `settings: { anthropicKeyStatus: () => req<AnthropicKeyStatus>('/settings/anthropic-key') }`
(add a `settings` group if not present; the existing plan-config calls live under `planConfig`,
keep that as-is and add `settings` for this status call).

**`pages/Settings.tsx`** — a new read-only card "Anthropic API Key":
- Queries `api.settings.anthropicKeyStatus()` via TanStack Query.
- Shows **✓ Configured** (green) or **● Not configured** (gray).
- One-line hint: *"Set it in the terminal: `backend/.venv/bin/python deploy/store_credentials.py --anthropic`"*.
- Matches the existing Settings card styling (Provider Aliases / Plan Configuration sections).

### Docs

- **`CLAUDE.md`** — update the `extraction.py` note: the key resolves Keychain → env var; set
  it via `deploy/store_credentials.py --anthropic`. Mention the new `claims-tracker-anthropic`
  Keychain service alongside the existing `claims-tracker-anthem` note.
- **`deploy/README.md`** — replace the plist `EnvironmentVariables` instructions as the primary
  path with the terminal command; keep the env-var/plist approach as a documented fallback.

## Data flow

```
Set:    terminal → store_credentials.py --anthropic → credentials.store_anthropic_key → Keychain
Use:    POST /api/submissions/extract → extract_submission_fields
          → key = Keychain (get_anthropic_key) or env ANTHROPIC_API_KEY
          → none: configured=False (UI: "PDF auto-fill unavailable")
          → found: anthropic.Anthropic(api_key=key) → extract
Status: Settings page → GET /api/settings/anthropic-key → { configured } → ✓ / ● badge
```

## Error handling / security

- The key is never accepted or returned over HTTP — only a boolean `configured` is exposed.
- `get_anthropic_key()` treats empty string as unset (returns `None`).
- Extraction's never-raises contract is unchanged; a missing key still degrades to manual entry.
- Keychain persists across reinstalls, unlike the plist env var (which `install.sh` would drop).

## Testing

- **`test_credentials.py`**: `store_anthropic_key`/`get_anthropic_key` roundtrip; `get_anthropic_key()`
  returns `None` when unset. (Reuse the existing keyring test setup / fake backend in that file.)
- **`test_extraction.py`**: key resolves from Keychain when present (stub
  `extraction.credentials.get_anthropic_key`); falls back to env var when Keychain returns `None`;
  `configured=False` when neither is set. Existing extraction tests that set the env var get a
  one-line tweak to stub `get_anthropic_key()` → `None` so they exercise the env path deterministically.
- **`test_settings.py` (or existing settings test module)**: `GET /settings/anthropic-key` returns
  `configured: true` when `get_anthropic_key()` is stubbed to a value and `false` when `None`.

## Out of scope (YAGNI)

- Any web endpoint that accepts or returns the key value.
- Migrating the Anthem credentials or the stale `data/credentials.json` settings route.
- A "test this key" / live-validation button.
