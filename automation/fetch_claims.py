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
_EXPORT_SELECTORS = [
    'button:has-text("Export")',
    'a:has-text("Export")',
    'button:has-text("Download")',
    'a:has-text("Download")',
    '[data-testid*="export" i]',
    '[aria-label*="export" i]',
    '[aria-label*="download" i]',
]


def download_claims_csv(page: Page) -> Path:
    print("Navigating to claims summary…")
    page.goto(CLAIMS_URL, wait_until="domcontentloaded", timeout=30_000)
    auth.check_for_site_error(page)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    dest = DATA_DIR / f"claims-{timestamp}.csv"

    print("Waiting for Export button…")
    with page.expect_download(timeout=30_000) as dl_info:
        _click_export(page)

    download = dl_info.value
    if download.failure():
        raise RuntimeError(f"Download failed: {download.failure()}")

    download.save_as(str(dest))
    print(f"Saved: {dest}")
    return dest


def _click_export(page: Page) -> None:
    for sel in _EXPORT_SELECTORS:
        try:
            page.click(sel, timeout=5_000)
            return
        except Exception:
            continue
    raise RuntimeError(
        "Could not find the Export button on the claims page.\n"
        f"URL: {CLAIMS_URL}\n"
        "Update _EXPORT_SELECTORS in fetch_claims.py to match Anthem's current UI."
    )


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
