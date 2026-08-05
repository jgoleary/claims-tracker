"""Session detection for the Anthem login flow.

Regression: login() decided "already logged in" from a URL snapshot. But an
already-authenticated session is served the member dashboard *at*
https://www.anthem.com/login — the URL still contains "login" while the page is
plainly signed in (a "Log Out" link, no form inputs at all). The URL check
therefore never fired, login() fell through to the Okta form, and _fill_first
burned 6 selectors x 10s before raising. Callers then sat in their
"leave the browser open" wait, which presented as a hang.

Detect the session from page content, the same way ih_auth._form_ready does.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "automation"))
import auth  # noqa: E402


LOGIN_URL = "https://www.anthem.com/login"
MEMBER_URL = "https://membersecure.anthem.com/member/home"
REDIRECT_URL = "https://www.anthem.com/auth-redirect?code=abc"


class _FakeLocator:
    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n


class _FakePage:
    """Serves a scripted set of selector counts, advancing on each poll."""

    def __init__(self, url, states):
        self.url = url
        self._states = states  # list of {selector: count}
        self._i = 0
        self.polls = 0

    def locator(self, sel):
        state = self._states[min(self._i, len(self._states) - 1)]
        return _FakeLocator(state.get(sel, 0))

    def wait_for_timeout(self, _ms):
        self.polls += 1
        self._i += 1


def _signed_in():
    return {'a:has-text("Log Out")': 1}


def _login_form():
    return {'input[name="identifier"]': 1}


def _blank():
    return {}


# ── the regression ───────────────────────────────────────────────────────────

def test_dashboard_served_at_login_url_is_detected_as_a_session():
    """The exact observed case: URL says /login, page is the member dashboard."""
    page = _FakePage(LOGIN_URL, [_signed_in()])
    assert auth.wait_for_login_or_session(
        page, timeout_ms=10_000, poll_ms=1, clock=lambda: 0.0) == "session"


def test_login_form_is_detected_as_a_form():
    page = _FakePage(LOGIN_URL, [_login_form()])
    assert auth.wait_for_login_or_session(
        page, timeout_ms=10_000, poll_ms=1, clock=lambda: 0.0) == "form"


def test_member_url_is_a_session_without_needing_content():
    page = _FakePage(MEMBER_URL, [_blank()])
    assert auth.wait_for_login_or_session(
        page, timeout_ms=10_000, poll_ms=1, clock=lambda: 0.0) == "session"


def test_auth_redirect_url_is_not_yet_a_session():
    """auth-redirect is mid-OAuth-exchange, not a settled session."""
    page = _FakePage(REDIRECT_URL, [_blank()])
    ticks = iter(range(0, 1000))
    assert auth.wait_for_login_or_session(
        page, timeout_ms=100, poll_ms=1, clock=lambda: next(ticks)) == "form"


def test_waits_for_a_slow_form_before_giving_up():
    # Nothing renders for two polls, then the identifier field appears.
    page = _FakePage(LOGIN_URL, [_blank(), _blank(), _login_form()])
    assert auth.wait_for_login_or_session(
        page, timeout_ms=10_000, poll_ms=1, clock=lambda: 0.0) == "form"
    assert page.polls >= 2


def test_falls_through_to_form_when_nothing_is_detectable():
    """Unknown page → behave as before and let the form flow raise its own
    clear error, rather than wrongly claiming a session."""
    page = _FakePage(LOGIN_URL, [_blank()])
    ticks = iter(range(0, 1000))
    assert auth.wait_for_login_or_session(
        page, timeout_ms=100, poll_ms=1, clock=lambda: next(ticks)) == "form"


# ── login() wiring ───────────────────────────────────────────────────────────

def test_login_returns_early_on_an_authenticated_dashboard(monkeypatch):
    """login() must not touch the form when a session is already live."""
    filled = []
    monkeypatch.setattr(auth, "_fill_first",
                        lambda *a, **k: filled.append(a[1] if len(a) > 1 else None))
    monkeypatch.setattr(auth, "_click_first", lambda *a, **k: filled.append("click"))
    monkeypatch.setattr(auth, "wait_for_login_or_session", lambda page, **k: "session")

    class _Page:
        url = LOGIN_URL

        def goto(self, *a, **k):
            pass

    auth.login(_Page(), "user", "pw")
    assert filled == [], "login() tried to fill the Okta form despite a live session"


def test_login_still_fills_the_form_when_there_is_no_session(monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "wait_for_login_or_session", lambda page, **k: "form")
    monkeypatch.setattr(auth, "_fill_first", lambda *a, **k: calls.append("fill"))
    monkeypatch.setattr(auth, "_click_first", lambda *a, **k: calls.append("click"))
    monkeypatch.setattr(auth, "check_for_site_error", lambda page: None)

    class _Page:
        url = MEMBER_URL

        def goto(self, *a, **k):
            pass

        def wait_for_url(self, *a, **k):
            pass

        def wait_for_load_state(self, *a, **k):
            pass

    auth.login(_Page(), "user", "pw")
    assert calls == ["fill", "click", "fill", "click"]
