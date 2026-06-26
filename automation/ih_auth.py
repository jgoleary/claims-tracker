"""Included Health login via the persistent browser profile.

IH authenticates through Google SSO, which blocks scripted credential entry, so
this never types a password: it opens the claims-support page in a headful
browser and — if no valid session exists — waits for the user to complete login
manually. The session persists in its own profile dir, so later runs skip login
until it expires (mirrors the Anthem MFA approach in auth.py)."""
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright

_PROFILE_DIR = Path(__file__).parent.parent / "data" / "browser-profile-ih"

CLAIMS_SUPPORT_URL = "https://member.includedhealth.com/claims-support?source=Service+Drawer"


def launch_context(pw: Playwright) -> BrowserContext:
    """Launch a persistent browser context so the IH/Google session survives runs."""
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(_PROFILE_DIR),
        headless=False,
        # Remove Playwright's automation fingerprint so Google doesn't block login.
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )


def _is_logged_in(page: Page) -> bool:
    url = page.url.lower()
    return "member.includedhealth.com" in url and "login" not in url


def login(page: Page, timeout: int = 180_000) -> None:
    """Open the claims-support page; if not authenticated, wait for the user to
    complete Google/IH login in the browser, then land back on claims-support."""
    print("Opening Included Health claims support…")
    page.goto(CLAIMS_SUPPORT_URL, wait_until="load", timeout=60_000)

    if _is_logged_in(page):
        print("Session still active — skipping login.")
        return

    print("Complete login in the browser window (Google sign-in / MFA if prompted)…")
    page.wait_for_url(lambda url: "member.includedhealth.com" in url.lower(), timeout=timeout)

    # After login IH may land on the home page — return to claims-support.
    if "claims-support" not in page.url:
        page.goto(CLAIMS_SUPPORT_URL, wait_until="load", timeout=60_000)

    page.wait_for_load_state("domcontentloaded", timeout=15_000)
    print("Logged in.")
