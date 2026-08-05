"""Shared credential loading and Anthem login flow."""
import getpass
import os
import sys
import time

from playwright.sync_api import BrowserContext, Page, Playwright

from pathlib import Path

_PROFILE_DIR = Path(__file__).parent.parent / "data" / "browser-profile"
_BACKEND_DIR = Path(__file__).parent.parent / "backend"

ANTHEM_LOGIN_URL = "https://www.anthem.com/login"
MEMBER_URL_PATTERN = "**/member/**"


def keychain_credentials() -> tuple[str, str] | None:
    """The Anthem credentials the backend stores in the macOS Keychain, if any.

    Only reached on manual runs: when the backend spawns these scripts it
    resolves the Keychain itself and injects ANTHEM_USERNAME/ANTHEM_PASSWORD.
    Any failure (no keyring, locked Keychain, nothing stored) is treated as
    "not available" so we fall through to prompting.
    """
    try:
        sys.path.insert(0, str(_BACKEND_DIR))
        from app import credentials

        return credentials.get_credentials()
    except Exception:
        return None


def get_credentials() -> tuple[str, str]:
    """Resolve credentials: env vars → macOS Keychain → interactive prompt."""
    username = os.environ.get("ANTHEM_USERNAME")
    password = os.environ.get("ANTHEM_PASSWORD")
    if username and password:
        return username, password

    stored = keychain_credentials()
    if stored:
        return stored

    username = username or input("Anthem email: ").strip()
    password = password or getpass.getpass("Anthem password: ")
    return username, password


def launch_context(pw: Playwright) -> BrowserContext:
    """Launch a persistent browser context so session cookies survive between runs."""
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(_PROFILE_DIR),
        headless=False,
        # Remove Playwright's automation fingerprint so Anthem doesn't detect a bot.
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )


def check_for_site_error(page: Page) -> None:
    """Raise a clear exception if Anthem is showing a transient error page."""
    if "unable to process your request" in (page.inner_text("body") or "").lower():
        raise RuntimeError(
            "Anthem returned a site error ('We're unable to process your request'). "
            "This is a transient issue on their end — wait a few minutes and try again."
        )




# Markers that Anthem has served a signed-in page.
_SESSION_SELECTORS = [
    'a:has-text("Log Out")',
    'button:has-text("Log Out")',
    'a:has-text("Log out")',
]

# The Okta identifier field — i.e. we really do have to log in.
_IDENTIFIER_SELECTORS = [
    'input[name="identifier"]',
    'input[type="email"]',
    'input[name="username"]',
    'input[id="username"]',
    'input[placeholder*="username" i]',
    'input[placeholder*="email" i]',
]


def _any_present(page: Page, selectors: list[str]) -> bool:
    for sel in selectors:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def wait_for_login_or_session(page: Page, timeout_ms: int = 15_000, poll_ms: int = 500,
                              clock=time.monotonic) -> str:
    """Return "session" if we're already signed in, else "form".

    The URL is NOT a usable signal here: an already-authenticated session is
    served the member dashboard *at* https://www.anthem.com/login, so page.url
    still contains "login" while the page is plainly signed in and has no form
    inputs at all. Key off content instead — the same lesson as
    ih_auth._form_ready. Falls back to "form" if neither settles, so an
    unrecognized page behaves as it always did and the form flow raises its own
    clear error.
    """
    if "/member/" in page.url and "auth-redirect" not in page.url:
        return "session"

    deadline = clock() + timeout_ms / 1000
    while True:
        if _any_present(page, _SESSION_SELECTORS):
            return "session"
        if _any_present(page, _IDENTIFIER_SELECTORS):
            return "form"
        if clock() >= deadline:
            return "form"
        page.wait_for_timeout(poll_ms)


def login(page: Page, username: str, password: str, mfa_timeout: int = 120_000) -> None:
    """Navigate to login, fill credentials, wait up to mfa_timeout ms for MFA completion.
    If a valid session cookie already exists, skips the login form entirely."""
    print("Opening Anthem login page…")
    page.goto(ANTHEM_LOGIN_URL, wait_until="load", timeout=30_000)

    if wait_for_login_or_session(page) == "session":
        print("Session still active — skipping login.")
        return

    # Okta-based login: identifier field, then Next, then password on next screen.
    _fill_first(page, [
        'input[name="identifier"]',
        'input[type="email"]',
        'input[name="username"]',
        'input[id="username"]',
        'input[placeholder*="username" i]',
        'input[placeholder*="email" i]',
    ], username, "username/email field")

    _click_first(page, [
        'input[type="submit"][value="Next"]',
        'input[type="submit"]',
        'button:has-text("Next")',
        'button:has-text("Continue")',
        'button[type="submit"]',
    ], "Next button")

    _fill_first(page, [
        'input[type="password"]',
        'input[name="password"]',
        'input[id="password"]',
    ], password, "password field")

    _click_first(page, [
        'input[type="submit"]',
        'button[type="submit"]',
    ], "sign-in button")

    print("Waiting for login to complete (complete MFA in the browser if prompted)…")
    page.wait_for_url(MEMBER_URL_PATTERN, timeout=mfa_timeout)

    # auth-redirect exchanges the OAuth code for session cookies — wait for it to finish.
    if "auth-redirect" in page.url:
        print("Completing auth redirect…")
        page.wait_for_url(
            lambda url: "/member/" in url and "auth-redirect" not in url,
            timeout=30_000,
        )

    page.wait_for_load_state("domcontentloaded", timeout=15_000)
    check_for_site_error(page)
    print("Logged in.")


def _fill_first(page: Page, selectors: list[str], value: str, name: str) -> None:
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=10_000, state="visible")
            if el:
                el.fill(value)
                return
        except Exception:
            continue
    raise RuntimeError(
        f"Could not find {name}.\n"
        f"Selectors tried: {selectors}\n"
        f"Update auth.py if Anthem changed their login page."
    )


def _click_first(
    page: Page, selectors: list[str], name: str, optional: bool = False
) -> None:
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=3_000, state="visible")
            if el:
                el.click()
                return
        except Exception:
            continue
    if not optional:
        raise RuntimeError(
            f"Could not find {name}.\n"
            f"Selectors tried: {selectors}\n"
            f"Update auth.py if Anthem changed their login page."
        )
