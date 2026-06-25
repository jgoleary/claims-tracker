# Easy Install — One-Command Setup for Non-Technical Mac Users

**Date:** 2026-06-24 **Status:** Approved design, pending spec review

## Problem

Installing Claims Tracker today requires a developer-grade ritual: clone the repo, create
a Python venv, `pip install`, `playwright install chromium`, run a Terminal script to
store credentials, then `bash deploy/install.sh` (which itself needs Node/npm to build the
frontend). The full baseline is captured in `INSTALL.md`. We want a Mac + Anthem user —
comfortable opening Terminal but not a developer — to go from nothing to a running app
with **one pasted command**, and to uninstall just as easily.

## Audience & scope (locked decisions)

- **Audience:** macOS users who also have Anthem OON claims (same setup as the
  maintainer). Comfortable opening Terminal and pasting one line; not developers.
- **Terminal is acceptable** — we are NOT building a `.app` bundle and NOT paying for
  Apple code signing/notarization.
- **Out of scope (YAGNI):** Windows/Linux, non-Anthem insurers, `.app`/DMG packaging,
  auto-update, GUI installer.

## Key insight: the Terminal path avoids Gatekeeper entirely

Gatekeeper's "unidentified developer / Open Anyway" wall fires only on a **quarantined**
file launched via **Finder/LaunchServices** (double-click) or exec'd directly. Two facts
let us sidestep it completely:

1. Files fetched by **curl** or a program's own HTTP client are **not quarantined**. So
   uv, the Python it downloads, and Playwright's Chromium never trigger Gatekeeper (this
   is already true of `playwright install chromium` today).
2. A script passed as an **argument to an interpreter** (`bash install.sh`) is read as
   _data_, not assessed by Gatekeeper — even if it came from a browser-downloaded zip.

Therefore the install must be invoked as **`curl … | bash`** or **`bash install.sh`**,
never double-clicked and never `./install.sh`. This removes the one-time "Open Anyway"
prompt that a `.command` file would still incur. The `.command` approach is rejected.

## Prerequisites after this change

Just **macOS + an internet connection**. No Xcode Command Line Tools, no system Python, no
Homebrew, no Node, no git:

- **Python** — uv downloads a pinned, self-contained modern Python (Astral's
  python-build-standalone). The codebase's existing 3.10+ requirement is satisfied; the
  `storage.py` `from __future__ import annotations` question is moot here (see Optional
  cleanup).
- **Node/npm** — eliminated by shipping a **prebuilt `frontend/dist`** in the release.
- **git** — eliminated; the source arrives as a release tarball via curl, not a clone.

## Components

Script locations: `deploy/make_release.sh`, `deploy/install.sh`, `deploy/uninstall.sh`
live in the repo/tarball. `bootstrap.sh` is published as a **standalone Release asset**
(it is what the one-liner curls) and, after extracting the tarball, calls
`bash deploy/install.sh` inside it.

### 1. `deploy/make_release.sh` (maintainer-only)

Run by the maintainer to publish a version. It:

- runs `npm run build` to produce `frontend/dist`,
- assembles a source tarball **including** the prebuilt `dist` (excluding `data/`,
  `.venv`, `node_modules`),
- publishes a GitHub Release with two assets: the **tarball** and a standalone
  **`bootstrap.sh`**.

This is the only place Node/npm ever runs.

### 2. `bootstrap.sh` (curl | bash entry point)

The target of the one-liner. It:

- picks an install location (default `~/claims-tracker`),
- downloads + extracts the release tarball via curl,
- runs `bash install.sh` inside it.

Kept thin so the heavy lifting lives in `install.sh` and is identical across both delivery
paths.

### 3. `deploy/install.sh` (the installer; runs from the unpacked bundle)

Replaces the role of today's `deploy/install.sh`. Idempotent — re-running it is the update
path. Steps:

1. `xattr -dr com.apple.quarantine` on the bundle (belt-and-suspenders; harmless).
2. Install **uv** if absent (`curl -LsSf https://astral.sh/uv/install.sh | sh`, pinned
   version).
3. `uv venv backend/.venv` with a pinned Python;
   `uv pip install -r backend/requirements.txt` (runtime deps, not `-dev`).
4. `playwright install chromium`.
5. Prompt for **Anthem** credentials (and optional **Anthropic** key) and write them
   straight to the **Keychain** via the existing `deploy/store_credentials.py` /
   `app.credentials` module — credentials never touch the web layer.
6. Install + load the two launchd agents from the existing plist templates, **skipping the
   npm build** because `frontend/dist` is prebuilt (error clearly if `dist` is missing).
7. `open http://localhost:8000` and print a short success summary, including the MFA note
   and the uninstall command.

### 4. `deploy/uninstall.sh` (+ documented in README)

- Unloads and removes both launchd agents (wraps existing `deploy/uninstall.sh` logic).
- **Keeps `data/` and Keychain credentials by default**; prints exactly how to remove them
  for a clean slate (delete the install folder; `store_credentials.py`/Keychain Access to
  drop the entries).
- Reachable two ways, mirroring install: `bash ~/claims-tracker/uninstall.sh`, or a curl
  one-liner.

### 5. Documentation restructure

- **Top of `README.md`** gains a short **"Install (macOS)"** section: the one-liner, the
  zip-+-`bash` alternative with the drag-the-file-into-Terminal tip, and an
  **"Uninstall"** subsection — all above the existing developer/Development content.
- The detailed manual/from-source process (current `INSTALL.md`) remains for developers;
  README links to it as "Manual / developer setup."

## Delivery: two entry points, one installer

Both published on the GitHub Release page:

- **One-liner (recommended for most):**
  `curl -fsSL https://github.com/<owner>/claims-tracker/releases/latest/download/bootstrap.sh | bash`
  Nothing is ever quarantined → zero Gatekeeper. Pin to a release tag rather than `latest`
  to avoid running unreviewed remote code.
- **Zip + Terminal (for the cautious):** download the tarball/zip from Releases, unzip,
  then `bash <unzipped>/install.sh`. Tip in the README: type `bash `, drag `install.sh`
  from Finder into Terminal to auto-fill the path, press Return. Lets them inspect files
  first; still no Gatekeeper because it's `bash <script>`.

## Inherent constraints (unchanged by this work)

- First refresh opens a **headful Chromium** for Anthem's Okta **MFA**; the Mac must be
  logged in for scheduled runs. This is Anthem-side and independent of packaging.
- First run downloads uv + a Python + Chromium (a few hundred MB); requires network.

## Error handling

- No network / failed download (uv, tarball, Chromium): fail with a clear, actionable
  message; the script is idempotent so re-running resumes cleanly.
- Missing `frontend/dist` (bad release artifact): explicit error pointing at
  `make_release.sh`, rather than silently serving nothing.
- Empty/cancelled credential prompts: existing `store_credentials.py` behavior (refuse to
  store blanks); install can continue and creds can be added later.

## Optional, orthogonal cleanup (NOT part of this plan)

`backend/app/storage.py` is the only backend file missing
`from __future__ import annotations`; its module-level `Storage | None` annotation is the
sole thing forcing a 3.10+ floor. Adding the import would make the app 3.9-compatible. The
uv approach makes this irrelevant for installation, so it is noted only as a possible
future simplification, not required here.

## Testing

- Dry-run `install.sh` on a clean macOS user account (no venv, no Node, no Homebrew
  Python) to confirm the "macOS + internet only" claim end-to-end.
- Confirm no Gatekeeper prompt appears via either entry point.
- Verify `uninstall.sh` unloads both agents and that re-running `install.sh` updates a
  prior install in place.
- Verify the prebuilt-`dist` path serves the SPA without npm present.
