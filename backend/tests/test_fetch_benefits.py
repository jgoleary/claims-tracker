"""Benefits scrape against Anthem's react-native-web benefits page.

Regression (observed 2026-09-26): Anthem shipped a rebuilt benefits micro-app
(release 2026-09-25). ?covtype=med redirects to /member/benefits/landing, and the
Angular tab bodies and .progress-bar-amount spans the old scraper waited on no
longer exist, so every refresh timed out. The "Plan details & progress" section
now lists both networks as data-testid'd progress cards inside collapsed
accordions. Fake Page/Locator duck types stand in for Playwright, so nothing
here launches a browser.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "automation"))
import fetch_benefits  # noqa: E402

_PREFIX = "benefits.networkProgressCard."


class _FakeCard:
    def __init__(self, fields):
        self._fields = fields  # testid suffix -> text

    def locator(self, sel):
        name = sel.split(_PREFIX, 1)[1].rstrip('"]')
        return _FakeText(self._fields.get(name))


class _FakeText:
    def __init__(self, text):
        self._text = text

    @property
    def first(self):
        return self

    def text_content(self, **_kw):
        if self._text is None:
            raise TimeoutError("no such field")
        return self._text


class _FakeCards:
    def __init__(self, cards):
        self._cards = cards

    def count(self):
        return len(self._cards)

    def nth(self, i):
        return self._cards[i]


def _card(network, total, spent):
    return _FakeCard({
        "networkDisplay": f"{network}: {total}",
        "totalValue": total,
        "spentValue": spent,
    })


# The live page on 2026-09-26 (family rows; figures match the last good export).
_LIVE = {
    "Deductible": [
        _card("Participating Network", "$3,400.00", "$3,400.00"),
        _card("Out of Network", "$6,800.00", "$3,400.00"),
    ],
    "OutOfPocketMaximum": [
        _card("Participating Network", "$5,200.00", "$4,281.05"),
        _card("Out of Network", "$10,400.00", "$4,281.05"),
    ],
}


class _FakePage:
    def __init__(self, sections, renders=True):
        self.url = fetch_benefits.BENEFITS_URL
        self._sections = sections
        self._renders = renders

    def goto(self, url, **_kw):
        self.url = url

    def inner_text(self, _sel):
        return ""

    def wait_for_selector(self, sel, **_kw):
        if not self._renders:
            raise TimeoutError("never rendered")
        return object()

    def locator(self, sel):
        for name, cards in self._sections.items():
            if fetch_benefits._SECTION.format(name) in sel:
                return _FakeCards(cards)
        return _FakeCards([])


@pytest.fixture(autouse=True)
def _no_site_error(monkeypatch):
    monkeypatch.setattr(fetch_benefits.auth, "check_for_site_error", lambda page: None)


def test_reads_both_networks_from_the_plan_details_cards():
    data = fetch_benefits.scrape_benefits(_FakePage(_LIVE))

    assert data == {
        "in_network": {
            "deductible_spent": "$3,400.00",
            "deductible_limit": "$3,400.00",
            "oop_spent": "$4,281.05",
            "oop_limit": "$5,200.00",
        },
        "out_of_network": {
            "deductible_spent": "$3,400.00",
            "deductible_limit": "$6,800.00",
            "oop_spent": "$4,281.05",
            "oop_limit": "$10,400.00",
        },
    }


def test_missing_network_card_names_what_to_edit():
    sections = dict(_LIVE, OutOfPocketMaximum=_LIVE["OutOfPocketMaximum"][:1])

    with pytest.raises(RuntimeError) as exc:
        fetch_benefits.scrape_benefits(_FakePage(sections))

    message = str(exc.value)
    assert "Out of Network" in message and "fetch_benefits.py" in message


def test_page_that_never_renders_names_what_to_edit():
    with pytest.raises(RuntimeError) as exc:
        fetch_benefits.scrape_benefits(_FakePage(_LIVE, renders=False))

    assert "_SECTION" in str(exc.value)


def test_signed_out_page_raises_session_rejected():
    page = _FakePage(_LIVE, renders=False)
    page.goto = lambda url, **_kw: setattr(page, "url", "https://www.anthem.com/")

    with pytest.raises(fetch_benefits.auth.SessionRejectedError):
        fetch_benefits.scrape_benefits(page)
