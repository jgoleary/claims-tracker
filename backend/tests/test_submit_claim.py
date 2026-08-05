"""Unit tests for the Anthem claim-submission wizard driver.

The wizard is driven by selectors that only a live run can validate; what these
tests pin down is the logic around them — patient matching, step ordering, and
the "never guess a patient" contract. Fake Page/Locator duck types stand in for
Playwright (the pattern from test_ih_auth.py), so nothing here launches a browser.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "automation"))
import submit_claim  # noqa: E402


# Real option text from Anthem's Patient Name dropdown (fictional household).
JOHN = "JOHN G O'LEARY (01/19/1981)"
NOLAN = "NOLAN F O'LEARY (02/14/2019)"
NEWBORN = "Newborn"
PLACEHOLDER = "Select a patient"
OPTIONS = [PLACEHOLDER, JOHN, NOLAN, NEWBORN]


# ── _normalize_name ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (JOHN, ("john", "oleary")),
    (NOLAN, ("nolan", "oleary")),
    (NEWBORN, ("newborn", "")),
    ("Nolan", ("nolan", "")),
    ("Nolan O'Leary", ("nolan", "oleary")),
    ("  nolan   o'leary  ", ("nolan", "oleary")),
    ("MARY JANE WATSON (03/03/1990)", ("mary", "watson")),  # keeps real middle names out of first/last
    ("", ("", "")),
])
def test_normalize_name(raw, expected):
    assert submit_claim._normalize_name(raw) == expected


def test_normalize_name_strips_middle_initial_not_middle_name():
    # Single-letter interior token is an initial and is dropped.
    assert submit_claim._normalize_name("JOHN G O'LEARY (01/19/1981)") == ("john", "oleary")
    # A full interior name is not the surname either — last token wins.
    assert submit_claim._normalize_name("MARY JANE WATSON") == ("mary", "watson")


# ── match_patient_options ────────────────────────────────────────────────────

def test_match_first_name_only_member():
    assert submit_claim.match_patient_options(OPTIONS, "Nolan") == [NOLAN]


def test_match_full_name_member():
    assert submit_claim.match_patient_options(OPTIONS, "John O'Leary") == [JOHN]


def test_match_ignores_case_and_punctuation():
    assert submit_claim.match_patient_options(OPTIONS, "john oleary") == [JOHN]


def test_match_single_token_option():
    assert submit_claim.match_patient_options(OPTIONS, "Newborn") == [NEWBORN]


def test_match_skips_the_placeholder_option():
    assert PLACEHOLDER not in submit_claim.match_patient_options(OPTIONS, "Select")


def test_match_returns_empty_when_no_first_name_matches():
    assert submit_claim.match_patient_options(OPTIONS, "Jordan") == []


def test_match_returns_empty_for_blank_member():
    assert submit_claim.match_patient_options(OPTIONS, "") == []


def test_match_rejects_right_first_name_wrong_surname():
    assert submit_claim.match_patient_options(OPTIONS, "Nolan Smith") == []


def test_match_allows_first_name_member_against_full_option():
    # Submission stores only "Nolan"; the option has a surname. Surname is only
    # compared when both sides have one.
    assert submit_claim.match_patient_options([NOLAN], "Nolan") == [NOLAN]


def test_match_returns_all_hits_when_ambiguous():
    twin = "NOLAN B SMITH (05/05/2020)"
    hits = submit_claim.match_patient_options([NOLAN, twin], "Nolan")
    assert hits == [NOLAN, twin]


# ── _one_match ───────────────────────────────────────────────────────────────

def test_one_match_returns_the_single_hit():
    assert submit_claim._one_match(OPTIONS, "Nolan") == NOLAN


def test_one_match_raises_on_zero_hits():
    with pytest.raises(submit_claim.AmbiguousPatientError) as e:
        submit_claim._one_match(OPTIONS, "Jordan")
    # The message must show what was offered so the user can act on it.
    assert "Jordan" in str(e.value)
    assert NOLAN in str(e.value)


def test_one_match_raises_on_multiple_hits():
    twin = "NOLAN B SMITH (05/05/2020)"
    with pytest.raises(submit_claim.AmbiguousPatientError):
        submit_claim._one_match([NOLAN, twin], "Nolan")


# ── Fake Playwright ──────────────────────────────────────────────────────────

# Clicking these navigates the wizard to its next page.
NAV_CLICKS = {"Get Started", "Next", "Continue", "Submit a Claim"}


class _FakeLocator:
    def __init__(self, page, name, count=1, texts=None, enabled=True, attrs=None):
        self._page = page
        self._name = name
        self._count = count
        self._texts = texts or []
        self._enabled = enabled
        self._attrs = attrs or {}

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def count(self):
        return self._count

    def locator(self, sel):
        return _FakeLocator(self._page, f"{self._name} {sel}", texts=self._texts)

    def click(self, **kw):
        if self._count == 0:
            raise RuntimeError(f"no element for {self._name}")
        self._page.log.append(("click", self._name))
        if self._name in NAV_CLICKS or self._name in self._page.nav_selectors:
            self._page.advance()

    def check(self, **kw):
        if self._count == 0:
            raise RuntimeError(f"no element for {self._name}")
        self._page.log.append(("check", self._name))

    def select_option(self, label=None, **kw):
        self._page.log.append(("select", label))

    def set_input_files(self, path, **kw):
        self._page.log.append(("upload", path))

    def all_text_contents(self):
        return self._texts

    def is_enabled(self):
        return self._enabled

    def get_attribute(self, name):
        return self._attrs.get(name)


class _FakePage:
    """Replays a scripted sequence of wizard pages.

    `bodies` is one body text per wizard screen; a click on a navigation control
    advances to the next one, which is what makes step ordering assertable.
    """

    url = "https://membersecure.anthem.com/member/claims/submission-questionnaire"

    def __init__(self, bodies, selectors=None, nav_selectors=(),
                 next_enabled_after=0, closed=True):
        self.bodies = bodies
        self.i = 0
        self.log = []
        # selector -> (count, texts)
        self.selectors = selectors or {}
        self.nav_selectors = set(nav_selectors)
        self.next_enabled_after = next_enabled_after
        self.polls = 0
        self.closed = closed

    def advance(self):
        self.i = min(self.i + 1, len(self.bodies) - 1)

    def inner_text(self, _sel):
        return self.bodies[self.i]

    def locator(self, sel):
        count, texts = self.selectors.get(sel, (0, []))
        return _FakeLocator(self, sel, count=count, texts=texts)

    def get_by_role(self, role, name=None, **kw):
        if role == "button" and name == "Next":
            enabled = self.polls >= self.next_enabled_after
            return _FakeLocator(self, "Next", enabled=enabled)
        if role == "option":
            count, texts = self.selectors.get("__options__", (0, []))
            return _FakeLocator(self, "option", count=count, texts=texts)
        return _FakeLocator(self, name or role)

    def get_by_text(self, text, **kw):
        return _FakeLocator(self, text)

    def wait_for_timeout(self, _ms):
        self.polls += 1

    def wait_for_event(self, _event, **kw):
        if not self.closed:
            raise TimeoutError("window never closed")
        self.log.append(("wait_for_close", None))

    def screenshot(self, **kw):
        pass


PDF = "/tmp/claim.pdf"

HAPPY_BODIES = [
    "Claim Submission Center Medical Dental Vision Get Started",
    "I want to submit a medical claim for Doctor or other medical specialist Next",
    f"Claims Submission Center Patient Name Select a patient {NOLAN}",
    "Claim Submission Requirements Next",
    "Step 1 of 5 Upload Your File(s) Select Document(s) to Upload",
    "Step 2 of 5 Processing File(s) Save & Exit Next",
    "Step 3 of 5 Claim Details",
]

# A native <select> holding the patient options.
NATIVE_SELECT = {"select": (1, OPTIONS)}


def _happy_page(**kw):
    return _FakePage(HAPPY_BODIES, selectors=dict(NATIVE_SELECT), **kw)


# ── fill_wizard ──────────────────────────────────────────────────────────────

def test_happy_path_action_sequence():
    page = _happy_page()
    submit_claim.fill_wizard(page, "Nolan", PDF)
    assert page.log == [
        ("click", "Get Started"),
        ("check", submit_claim._DOCTOR_OPTION),
        ("click", "Next"),               # claim type
        ("select", NOLAN),
        ("click", "Submit a Claim"),
        ("click", "Next"),               # requirements
        ("upload", PDF),
        ("click", "Next"),               # upload
        ("click", "Next"),               # processing
        ("wait_for_close", None),
    ]


def test_reaches_the_handoff_page():
    page = _happy_page()
    submit_claim.fill_wizard(page, "Nolan", PDF)
    assert "Step 3 of 5" in page.bodies[page.i]


def test_ambiguous_patient_stops_before_submit_a_claim():
    """The 'never guess a patient' contract: no claim record is created."""
    bodies = list(HAPPY_BODIES)
    twin = "NOLAN B SMITH (05/05/2020)"
    page = _FakePage(bodies, selectors={"select": (1, [PLACEHOLDER, NOLAN, twin])})
    with pytest.raises(submit_claim.AmbiguousPatientError):
        submit_claim.fill_wizard(page, "Nolan", PDF)
    assert ("click", "Submit a Claim") not in page.log
    assert ("upload", PDF) not in page.log


def test_unknown_patient_stops_before_submit_a_claim():
    page = _happy_page()
    with pytest.raises(submit_claim.AmbiguousPatientError):
        submit_claim.fill_wizard(page, "Jordan", PDF)
    assert ("click", "Submit a Claim") not in page.log


def test_dry_run_stops_before_submit_a_claim():
    page = _happy_page()
    submit_claim.fill_wizard(page, "Nolan", PDF, dry_run=True)
    assert ("select", NOLAN) in page.log
    assert ("click", "Submit a Claim") not in page.log
    assert ("upload", PDF) not in page.log


def test_custom_widget_branch_selects_by_option_text():
    # No native <select>; an ARIA combobox exposes role=option instead.
    page = _FakePage(
        HAPPY_BODIES,
        selectors={'[role="combobox"]': (1, []), "__options__": (len(OPTIONS), OPTIONS)},
    )
    submit_claim.fill_wizard(page, "Nolan", PDF)
    assert ("click", NOLAN) in page.log          # picked by option text
    assert ("click", "Submit a Claim") in page.log


def test_medical_card_selector_preferred_over_positional_fallback():
    sel = submit_claim._MEDICAL_GET_STARTED[0]
    page = _FakePage(HAPPY_BODIES, selectors={**NATIVE_SELECT, sel: (1, [])},
                     nav_selectors=[sel])
    submit_claim.fill_wizard(page, "Nolan", PDF)
    assert page.log[0] == ("click", sel)


def test_patient_selection_that_does_not_take_effect_raises():
    # Body never shows the chosen patient — a click that landed on nothing.
    bodies = list(HAPPY_BODIES)
    bodies[2] = "Claims Submission Center Patient Name Select a patient"
    page = _FakePage(bodies, selectors=dict(NATIVE_SELECT))
    with pytest.raises(RuntimeError, match="did not take effect"):
        submit_claim.fill_wizard(page, "Nolan", PDF)


def test_draft_block_raises_immediately_instead_of_timing_out():
    """Anthem diverts the wizard to its draft list when an unfinished draft
    exists; that must be reported, not waited out."""
    bodies = list(HAPPY_BODIES)
    bodies[2] = ("Claims Submission Center You must continue or delete your draft "
                 "submissions before you can submit a new claim Draft Submission")
    page = _FakePage(bodies, selectors=dict(NATIVE_SELECT))
    with pytest.raises(submit_claim.DraftSubmissionBlockedError, match="Continue that draft"):
        submit_claim.fill_wizard(page, "Nolan", PDF)
    assert ("click", "Submit a Claim") not in page.log


def test_draft_block_detected_while_waiting_for_any_page():
    page = _FakePage(["You must continue or delete your draft submissions first"])
    with pytest.raises(submit_claim.DraftSubmissionBlockedError):
        submit_claim._wait_for_page(page, "Get Started", "the start page",
                                    timeout_ms=60_000, poll_ms=1, clock=lambda: 0.0)


def test_wait_for_page_times_out_naming_the_script():
    page = _FakePage(["nothing useful here"])
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError, match="submit_claim.py"):
        submit_claim._wait_for_page(page, "Get Started", "the start page",
                                    timeout_ms=1_000, poll_ms=1,
                                    clock=lambda: next(ticks))


# ── wait_for_next_enabled ────────────────────────────────────────────────────

def _processing_page(**kw):
    return _FakePage(["Step 2 of 5 Processing File(s) Next"], **kw)


def test_wait_for_next_enabled_returns_once_enabled():
    page = _processing_page(next_enabled_after=2)
    assert submit_claim.wait_for_next_enabled(
        page, timeout_ms=60_000, poll_ms=1, clock=lambda: 0.0) is True
    assert page.polls >= 2


def test_wait_for_next_enabled_treats_aria_disabled_as_disabled():
    """is_enabled() is True but aria-disabled says otherwise — the likeliest
    real-world defect, since Playwright only knows the native attribute."""
    class _AriaPage(_FakePage):
        def get_by_role(self, role, name=None, **kw):
            return _FakeLocator(self, "Next", enabled=True,
                                attrs={"aria-disabled": "true"})

    page = _AriaPage(["Step 2 of 5 Processing File(s) Next"])
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError, match="never became enabled"):
        submit_claim.wait_for_next_enabled(page, timeout_ms=1_000, poll_ms=1,
                                           clock=lambda: next(ticks))


def test_wait_for_next_enabled_treats_disabled_class_as_disabled():
    class _ClassPage(_FakePage):
        def get_by_role(self, role, name=None, **kw):
            return _FakeLocator(self, "Next", enabled=True,
                                attrs={"class": "btn btn-primary disabled"})

    page = _ClassPage(["Step 2 of 5 Processing File(s) Next"])
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError, match="never became enabled"):
        submit_claim.wait_for_next_enabled(page, timeout_ms=1_000, poll_ms=1,
                                           clock=lambda: next(ticks))


def test_wait_for_next_enabled_detects_auto_advance():
    page = _FakePage(["Step 3 of 5 Claim Details"])
    assert submit_claim.wait_for_next_enabled(
        page, timeout_ms=1_000, poll_ms=1, clock=lambda: 0.0) is False


@pytest.mark.parametrize("banner", ["could not be processed", "upload failed",
                                    "unsupported file"])
def test_wait_for_next_enabled_raises_on_rejection_banner(banner):
    page = _FakePage([f"Step 2 of 5 Processing File(s) {banner}"])
    with pytest.raises(RuntimeError, match="rejected the uploaded PDF"):
        submit_claim.wait_for_next_enabled(page, timeout_ms=1_000, poll_ms=1,
                                           clock=lambda: 0.0)


def test_wait_for_next_enabled_times_out_naming_the_script():
    page = _processing_page(next_enabled_after=10_000)
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError, match="submit_claim.py"):
        submit_claim.wait_for_next_enabled(page, timeout_ms=1_000, poll_ms=1,
                                           clock=lambda: next(ticks))
