"""Shared credential loading and Anthem login flow."""
import getpass
import os
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page, Playwright

from pathlib import Path

PROFILE_DIR = Path(__file__).parent.parent / "data" / "browser-profile"
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
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=False,
        # Remove Playwright's automation fingerprint so Anthem doesn't detect a bot.
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )


def clear_http_cache(page: Page) -> bool:
    """Drop the persistent profile's HTTP cache. Returns True if it worked.

    A corrupted entry in data/browser-profile's cache serves a truncated script,
    the micro-app dies on a JS parse error, and the page renders as bare header
    and footer with no content — indistinguishable from a UI change until you
    look at the console. Session cookies live outside the HTTP cache, so this
    does not log us out. Chromium only exposes cache clearing over CDP.
    """
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Network.clearBrowserCache")
        return True
    except Exception as e:  # a failed recovery attempt must not mask the real error
        print(f"  Note: could not clear the browser cache ({e}).")
        return False


def check_for_site_error(page: Page) -> None:
    """Raise a clear exception if Anthem is showing a transient error page."""
    if "unable to process your request" in (page.inner_text("body") or "").lower():
        raise RuntimeError(
            "Anthem returned a site error ('We're unable to process your request'). "
            "This is a transient issue on their end — wait a few minutes and try again."
        )


# Every signed-in member page lives on this host.
_MEMBER_HOST = "membersecure.anthem.com"


class SessionRejectedError(RuntimeError):
    """Anthem signed us out after a login that appeared to succeed."""


def check_session_alive(page: Page) -> None:
    """Raise SessionRejectedError if Anthem has bounced us off the member portal.

    Observed 2026-09-26: Okta accepted the login and redirected back, then the
    portal's bootstrap API answered 401 "Authentication error" and the app sent
    the browser to logout.html and on to the public www.anthem.com home page.
    Nothing on that page is ours, so without this check the next step waits on
    selectors that can never appear (or, worse, matches a public-site look-alike)
    and fails with an error that points at the wrong thing.
    """
    url = page.url or ""
    if "logout.html" in url or urlparse(url).hostname != _MEMBER_HOST:
        raise SessionRejectedError(
            "Anthem signed the session out right after login "
            f"(the browser ended up at {url}). The portal rejected a session Okta "
            "had accepted — either an outage on Anthem's end, or stale cookies in "
            f"{PROFILE_DIR}. Check that the portal works in a normal browser; if it "
            "does, move that profile directory aside and run again (MFA will be "
            "needed once)."
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


def is_signed_in_url(url: str) -> bool:
    """True for a member page, False while the OAuth hand-off is still in flight.

    Everything under /member/public/ is part of that hand-off: auth-redirect,
    and — since 2026-09 — a second hop, authentication/oauth-callback, where the
    app exchanges the code for the session. Leaving that page early (a goto to
    the claims page, say) abandons the exchange; the next API call then 401s and
    Anthem signs the browser out to logout.html. Only a /member/ page outside
    /member/public/ (the dashboard, normally) means the session is established.
    """
    path = urlparse(url).path
    return path.startswith("/member/") and not path.startswith("/member/public/")


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
    if is_signed_in_url(page.url):
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

    # The OAuth hops (auth-redirect, then oauth-callback) establish the session —
    # wait until the app has left them for a signed-in page.
    if not is_signed_in_url(page.url):
        print("Completing auth redirect…")
        page.wait_for_url(is_signed_in_url, timeout=30_000)

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
