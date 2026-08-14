"""Claims download: recovery from a poisoned browser-profile HTTP cache.

Regression (observed 2026-08-13): the claims micro-app started rendering an
empty body — header and footer only, no table and no Export button — while the
benefits page in the same run kept working. Nothing had changed on our side
since the last good export. The page threw a JS "Invalid or unexpected token"
parse error, i.e. Chromium was serving a corrupted script out of
data/browser-profile's HTTP cache. Clearing that cache and reloading brought the
page back immediately (body 483 chars -> 3944, Export button present).

download_claims_csv() therefore gates on the Export button rendering, and on a
blank render clears the HTTP cache and reloads once before giving up. Fake
Page/Locator duck types stand in for Playwright (the pattern from
test_submit_claim.py), so nothing here launches a browser.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "automation"))
import fetch_claims  # noqa: E402


class _FakeLocator:
    def __init__(self, page, present):
        self._page = page
        self._present = present

    @property
    def first(self):
        return self

    def click(self, **_kw):
        if not self._present:
            raise RuntimeError("no such element")
        self._page.clicks += 1


class _FakeDownload:
    def __init__(self, page):
        self._page = page

    def failure(self):
        return None

    def save_as(self, dest):
        self._page.saved_to = dest


class _FakeDownloadCtx:
    def __init__(self, page):
        self._page = page

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def value(self):
        return _FakeDownload(self._page)


class _FakePage:
    """Renders the Export button only once `renders_after_loads` loads have happened.

    Models the observed failure: the first load serves the poisoned bundle and
    renders nothing; a load after the cache is cleared renders normally.
    """

    def __init__(self, renders_after_loads=0, body="Skip To Main Content"):
        self.url = fetch_claims.CLAIMS_URL
        self.loads = 0
        self.clicks = 0
        self.saved_to = None
        self.cache_clears = 0
        self._renders_after = renders_after_loads
        self._body = body

    # ── the bits fetch_claims touches ────────────────────────────────────────
    def goto(self, url, **_kw):
        self.loads += 1
        self.url = url

    def inner_text(self, _sel):
        return self._body

    def _rendered(self):
        return self.loads > self._renders_after

    def wait_for_selector(self, _sel, **_kw):
        if not self._rendered():
            raise TimeoutError("selector never appeared")
        return object()

    def locator(self, _sel):
        return _FakeLocator(self, self._rendered())

    def expect_download(self, **_kw):
        return _FakeDownloadCtx(self)


@pytest.fixture(autouse=True)
def _no_real_cdp(monkeypatch):
    """auth.clear_http_cache needs a real CDP session; record calls instead."""
    def _clear(page):
        page.cache_clears += 1
        return True

    monkeypatch.setattr(fetch_claims.auth, "clear_http_cache", _clear)
    monkeypatch.setattr(fetch_claims.auth, "check_for_site_error", lambda page: None)


@pytest.fixture(autouse=True)
def _tmp_export_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_claims, "DATA_DIR", tmp_path / "exports")


# ── the regression ───────────────────────────────────────────────────────────

def test_blank_claims_page_clears_the_cache_and_retries():
    """The exact observed case: first render is empty, a cache-clearing reload fixes it."""
    page = _FakePage(renders_after_loads=1)

    dest = fetch_claims.download_claims_csv(page)

    assert page.cache_clears == 1, "did not clear the poisoned HTTP cache"
    assert page.loads == 2, "did not reload after clearing the cache"
    assert page.clicks == 1, "never clicked Export after recovery"
    assert page.saved_to == str(dest)


def test_healthy_page_does_not_clear_the_cache():
    """A page that renders normally must take the fast path untouched."""
    page = _FakePage(renders_after_loads=0)

    fetch_claims.download_claims_csv(page)

    assert page.cache_clears == 0
    assert page.loads == 1
    assert page.clicks == 1


def test_still_blank_after_a_cache_clear_raises_a_diagnostic_error():
    """Never retry forever: one clear, then a message naming what to edit."""
    page = _FakePage(renders_after_loads=99)

    with pytest.raises(RuntimeError) as exc:
        fetch_claims.download_claims_csv(page)

    message = str(exc.value)
    assert page.cache_clears == 1, "should still have attempted the cache recovery"
    assert page.loads == 2, "should have retried exactly once"
    assert "_EXPORT_SELECTORS" in message and "fetch_claims.py" in message
    assert "cache" in message.lower(), "error should say the cache retry was already tried"
