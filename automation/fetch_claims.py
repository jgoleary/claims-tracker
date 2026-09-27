"""Download the Anthem claims CSV and ingest it into the backend."""
import sys
from pathlib import Path

# Allow running directly or via fetch_all.py regardless of cwd.
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime

import requests
from playwright.sync_api import Page, sync_playwright

import auth

CLAIMS_URL = "https://membersecure.anthem.com/member/claims"
BACKEND_URL = "http://localhost:8000"
DATA_DIR = Path("data/exports")

# Selectors for the Export button. Update if Anthem changes their UI.
# No bare "Download" link or aria-label: the site chrome carries several
# "Download the Sydney Health App" promo links, and on 2026-09-26 those matched
# on a signed-out page, so the wait passed and the click opened a new tab.
_EXPORT_SELECTORS = [
    'button:has-text("Export")',
    'a:has-text("Export")',
    'button:has-text("Download")',
    '[data-testid*="export" i]',
    '[aria-label*="export" i]',
]

# Playwright unions comma-separated selectors, so one wait covers all of them.
_EXPORT_SELECTOR = ", ".join(_EXPORT_SELECTORS)

# The claims micro-app renders well inside this; only a broken bundle never does.
_EXPORT_TIMEOUT_MS = 30_000


def download_claims_csv(page: Page) -> Path:
    print("Navigating to claims summary…")
    page.goto(CLAIMS_URL, wait_until="domcontentloaded", timeout=30_000)
    auth.check_for_site_error(page)

    print("Waiting for Export button…")
    if not _wait_for_export(page):
        # Signed out is not a cache problem — say so instead of clearing it.
        auth.check_session_alive(page)
        # An empty claims page is far more often a poisoned HTTP cache than a UI
        # change: a corrupted cached script kills the micro-app and Anthem serves
        # a bare header and footer. Clear the cache and reload once before
        # blaming the selectors.
        print("  Claims page rendered empty — clearing the browser cache and retrying…")
        auth.clear_http_cache(page)
        page.goto(CLAIMS_URL, wait_until="domcontentloaded", timeout=30_000)
        auth.check_for_site_error(page)
        if not _wait_for_export(page):
            auth.check_session_alive(page)
            raise RuntimeError(
                "Could not find the Export button on the claims page, including "
                "after clearing the browser cache and reloading.\n"
                f"URL: {CLAIMS_URL}\n"
                "If the page is visibly empty, check the browser console for a JS "
                f"error and try deleting the profile at {auth.PROFILE_DIR}.\n"
                "Otherwise update _EXPORT_SELECTORS in fetch_claims.py to match "
                "Anthem's current UI."
            )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    dest = DATA_DIR / f"claims-{timestamp}.csv"

    auth.check_session_alive(page)
    with page.expect_download(timeout=30_000) as dl_info:
        page.locator(_EXPORT_SELECTOR).first.click(timeout=10_000)

    download = dl_info.value
    if download.failure():
        raise RuntimeError(f"Download failed: {download.failure()}")

    download.save_as(str(dest))
    print(f"Saved: {dest}")
    return dest


def _wait_for_export(page: Page, timeout_ms: int = _EXPORT_TIMEOUT_MS) -> bool:
    """True once an Export control has rendered — i.e. the claims app is alive."""
    try:
        page.wait_for_selector(_EXPORT_SELECTOR, timeout=timeout_ms, state="visible")
        return True
    except Exception:
        return False


def post_csv(path: Path) -> bool:
    """POST the CSV to the backend. Returns True on success, prints curl fallback on failure."""
    try:
        with open(path, "rb") as f:
            resp = requests.post(
                f"{BACKEND_URL}/api/ingest/claims-csv",
                files={"file": (path.name, f, "text/csv")},
                timeout=30,
            )
        resp.raise_for_status()
        result = resp.json()
        print(
            f"Ingested: {result['new']} new, {result['updated']} updated, "
            f"{result['auto_matched']} auto-matched, {result['suggestions']} suggestions"
        )
        return True
    except Exception as e:
        print(f"Could not POST to backend ({e}). Upload manually:")
        print(f"  curl -X POST {BACKEND_URL}/api/ingest/claims-csv -F 'file=@{path.resolve()}'")
        return False


def run(page: Page) -> Path:
    """Download the CSV. Call post_csv() separately to ingest it."""
    return download_claims_csv(page)


def main() -> None:
    username, password = auth.get_credentials()
    with sync_playwright() as pw:
        context = auth.launch_context(pw)
        page = context.new_page()
        try:
            auth.login(page, username, password)
            csv_path = run(page)
            post_csv(csv_path)
        finally:
            context.close()


if __name__ == "__main__":
    main()
