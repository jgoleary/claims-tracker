"""Unit tests for the Included Health login-readiness logic.

Regression: login() used to decide "already logged in" from a URL snapshot taken
at the page-load event, which fires on the member shell *before* the SPA redirects
an expired session to login.includedhealth.com. That false positive made the
script skip the login wait and then fail on the form. login() must instead wait
for the real claims-support form (the "Out-of-network charges" option) to appear,
giving the user time to log in.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "automation"))
import ih_auth  # noqa: E402


class _FakeLocator:
    def __init__(self, n):
        self._n = n

    @property
    def first(self):
        return self

    def count(self):
        return self._n


class _FakePage:
    """Drives login() through a scripted sequence of (url, oon_count) states.
    Each wait_for_timeout advances to the next state (last state repeats)."""
    def __init__(self, states):
        self._states = states
        self._i = 0
        self.gotos = []

    @property
    def url(self):
        return self._states[min(self._i, len(self._states) - 1)][0]

    def goto(self, url, **kwargs):
        self.gotos.append(url)

    def get_by_text(self, *args, **kwargs):
        return _FakeLocator(self._states[min(self._i, len(self._states) - 1)][1])

    def wait_for_timeout(self, ms):
        self._i += 1


LOGIN_URL = ("https://login.includedhealth.com/login?redirect_uri="
             "https%3A%2F%2Fmember.includedhealth.com")
FORM_URL = "https://member.includedhealth.com/claims-support?source=Service+Drawer"
HOME_URL = "https://member.includedhealth.com/"


def test_on_member_rejects_login_page_with_member_redirect_param():
    assert ih_auth._on_member(LOGIN_URL) is False


def test_on_member_accepts_real_member_pages():
    assert ih_auth._on_member(FORM_URL) is True
    assert ih_auth._on_member(HOME_URL) is True


def test_login_waits_for_form_then_returns():
    # Starts on the login page (no form), user logs in, form finally renders.
    page = _FakePage([
        (LOGIN_URL, 0),
        (LOGIN_URL, 0),
        (FORM_URL, 1),
    ])
    ih_auth.login(page, timeout_ms=10_000, poll_ms=1, clock=lambda: 0.0)
    # Returned without raising — i.e. it did NOT falsely skip login at the start.


def test_login_renavigates_to_form_after_landing_on_member_home():
    page = _FakePage([
        (LOGIN_URL, 0),
        (HOME_URL, 0),   # logged in but on home page → should re-goto the form
        (FORM_URL, 1),
    ])
    ih_auth.login(page, timeout_ms=10_000, poll_ms=1, clock=lambda: 0.0)
    assert FORM_URL in page.gotos[1:]  # re-navigated after the initial goto


def test_login_times_out_when_form_never_appears():
    page = _FakePage([(LOGIN_URL, 0)])
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError):
        ih_auth.login(page, timeout_ms=1_000, poll_ms=1, clock=lambda: next(ticks))
