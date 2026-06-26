"""Included Health login via the persistent browser profile.

IH authenticates through Google SSO, which blocks scripted credential entry, so
this never types a password: it opens the claims-support page in a headful
browser and — if no valid session exists — waits for the user to complete login
manually. The session persists in its own profile dir, so later runs skip login
until it expires (mirrors the Anthem MFA approach in auth.py)."""
import time
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


def _on_member(url: str) -> bool:
    """True only for a genuine member.includedhealth.com page — NOT the login
    page, whose URL embeds member.includedhealth.com in its redirect_uri param."""
    u = (url or "").lower()
    return "member.includedhealth.com" in u and "login.includedhealth.com" not in u


def _form_ready(page: Page) -> bool:
    """True once the claims-support form has rendered. We key off the form's first
    option rather than the URL: an expired session briefly shows the member shell
    URL before the SPA redirects to login, so a URL snapshot gives false positives."""
    try:
        return page.get_by_text("Out-of-network charges", exact=False).count() > 0
    except Exception:
        return False


def login(page: Page, timeout_ms: int = 300_000, poll_ms: int = 1_500,
          clock=time.monotonic) -> None:
    """Open the claims-support page and wait until its form is actually present.

    Does NOT decide "logged in" from the URL — it polls for the form. If the
    session has expired the user sees the login screen and can sign in (Google /
    Apple / email) in the open browser window; once they land back on a member
    page we re-open the form. Raises if the form never appears within timeout_ms."""
    print("Opening Included Health claims support…")
    page.goto(CLAIMS_SUPPORT_URL, wait_until="domcontentloaded", timeout=60_000)
    print("If a login screen appears, sign in (Google / Apple / email) in the browser window…")

    deadline = clock() + timeout_ms / 1000
    while True:
        if _form_ready(page):
            print("Claims-support form ready.")
            return
        # Logged in but bounced to the member home page — go back to the form.
        if _on_member(page.url) and "/claims-support" not in page.url.lower():
            try:
                page.goto(CLAIMS_SUPPORT_URL, wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                pass
        if clock() >= deadline:
            raise RuntimeError(
                "Timed out waiting for the Included Health claims-support form. "
                "Was login completed in the browser window?"
            )
        page.wait_for_timeout(poll_ms)
