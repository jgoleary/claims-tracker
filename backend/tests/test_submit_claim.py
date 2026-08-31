"""Unit tests for the Anthem claim-submission wizard driver.

The wizard is driven by selectors that only a live run can validate; what these
tests pin down is the logic around them — patient matching, step ordering, and
the "never guess a patient" contract. Fake Page/Locator duck types stand in for
Playwright (the pattern from test_ih_auth.py), so nothing here launches a browser.

Anthem rebuilt this flow as a react-native-web micro-app in 2026-08: controls are
<div>s with a role and a data-testid, and each step is now identified by a
step-unique selector rather than by heading text. The fake models that — a step
is a set of selectors that exist on it — because the failure these tests exist to
prevent is acting on a step before the SPA has rendered it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "automation"))
import submit_claim  # noqa: E402


# Option text from Anthem's patient dropdown. Invented household — never put
# real patient names in fixtures. Anthem dropped the trailing (DOB) in the
# 2026-08 redesign, so these are bare names; DOB_* covers the legacy form,
# which _normalize_name still tolerates.
ALVAREZ = "MARIA T ALVAREZ"
DIEGO = "DIEGO R ALVAREZ"
ETINA = "NATALYA ETINA"
NEWBORN = "Newborn"
PLACEHOLDER = "Select a patient"
OPTIONS = [ETINA, ALVAREZ, DIEGO, NEWBORN]

DOB_ALVAREZ = "MARIA T ALVAREZ (01/19/1981)"
DOB_DIEGO = "DIEGO R ALVAREZ (02/14/2019)"


# ── _normalize_name ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (ALVAREZ, ("maria", "alvarez")),
    (DIEGO, ("diego", "alvarez")),
    (DOB_ALVAREZ, ("maria", "alvarez")),      # legacy "(DOB)" form still parses
    (DOB_DIEGO, ("diego", "alvarez")),
    (NEWBORN, ("newborn", "")),
    ("Diego", ("diego", "")),
    ("Diego Alvarez", ("diego", "alvarez")),
    ("  diego   alvarez  ", ("diego", "alvarez")),
    ("MARIA JANE O'CONNOR", ("maria", "oconnor")),  # punctuation dropped
    ("", ("", "")),
])
def test_normalize_name(raw, expected):
    assert submit_claim._normalize_name(raw) == expected


def test_normalize_name_strips_middle_initial_not_middle_name():
    # Single-letter interior token is an initial and is dropped.
    assert submit_claim._normalize_name("MARIA T ALVAREZ (01/19/1981)") == ("maria", "alvarez")
    # A full interior name is not the surname either — last token wins.
    assert submit_claim._normalize_name("MARIA JANE WATSON") == ("maria", "watson")


# ── match_patient_options ────────────────────────────────────────────────────

def test_match_first_name_only_member():
    assert submit_claim.match_patient_options(OPTIONS, "Diego") == [DIEGO]


def test_match_full_name_member():
    assert submit_claim.match_patient_options(OPTIONS, "Maria Alvarez") == [ALVAREZ]


def test_match_ignores_case_and_punctuation():
    assert submit_claim.match_patient_options(OPTIONS, "maria alvarez") == [ALVAREZ]


def test_match_single_token_option():
    assert submit_claim.match_patient_options(OPTIONS, "Newborn") == [NEWBORN]


def test_match_skips_the_placeholder_option():
    assert PLACEHOLDER not in submit_claim.match_patient_options(
        [PLACEHOLDER] + OPTIONS, "Select")


def test_match_returns_empty_when_no_first_name_matches():
    assert submit_claim.match_patient_options(OPTIONS, "Jordan") == []


def test_match_returns_empty_for_blank_member():
    assert submit_claim.match_patient_options(OPTIONS, "") == []


def test_match_rejects_right_first_name_wrong_surname():
    assert submit_claim.match_patient_options(OPTIONS, "Diego Smith") == []


def test_match_allows_first_name_member_against_full_option():
    # Submission stores only "Diego"; the option has a surname. Surname is only
    # compared when both sides have one.
    assert submit_claim.match_patient_options([DIEGO], "Diego") == [DIEGO]


def test_match_returns_all_hits_when_ambiguous():
    twin = "DIEGO B SMITH"
    hits = submit_claim.match_patient_options([DIEGO, twin], "Diego")
    assert hits == [DIEGO, twin]


def test_match_without_dob_still_separates_same_first_name_by_surname():
    """Anthem removed the (DOB) suffix, so surnames are the only discriminator
    left between two household members sharing a first name."""
    other = "DIEGO P NGUYEN"
    assert submit_claim.match_patient_options([DIEGO, other], "Diego Nguyen") == [other]


# ── _one_match ───────────────────────────────────────────────────────────────

def test_one_match_returns_the_single_hit():
    assert submit_claim._one_match(OPTIONS, "Diego") == DIEGO


def test_one_match_raises_on_zero_hits():
    with pytest.raises(submit_claim.AmbiguousPatientError) as e:
        submit_claim._one_match(OPTIONS, "Jordan")
    # The message must show what was offered so the user can act on it.
    assert "Jordan" in str(e.value)
    assert DIEGO in str(e.value)


def test_one_match_raises_on_multiple_hits():
    twin = "DIEGO B ALVAREZ"
    with pytest.raises(submit_claim.AmbiguousPatientError):
        submit_claim._one_match([DIEGO, twin], "Diego")


# ── Fake Playwright ──────────────────────────────────────────────────────────

SC = submit_claim

# Clicking one of these advances the wizard to its next step.
NAV_SELECTORS = {
    SC._MEDICAL_GET_STARTED[0],
    SC._CLAIM_TYPE_NEXT[0],
    SC._PATIENT_NEXT[0],
    SC._UPLOAD_NEXT[0],
    SC._PROCESSING_CONTINUE[0],
}


class _FakeLocator:
    def __init__(self, page, name, count=1, texts=None, enabled=True, attrs=None,
                 advances=False, on_click=None):
        self._page = page
        self._name = name
        self._count = count
        self._texts = texts or []
        self._enabled = enabled
        self._attrs = attrs or {}
        self._advances = advances
        self._on_click = on_click

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
        if self._on_click:
            self._on_click()
        if self._advances or self._name in NAV_SELECTORS:
            self._page.advance()

    def check(self, **kw):
        if self._count == 0:
            raise RuntimeError(f"no element for {self._name}")
        self._page.log.append(("check", self._name))

    def set_input_files(self, path, **kw):
        if self._count == 0:
            raise RuntimeError(f"no element for {self._name}")
        self._page.log.append(("upload", path))

    def all_text_contents(self):
        return self._texts

    def input_value(self, **kw):
        if "value" not in self._attrs:
            raise RuntimeError(f"{self._name} is not an input")
        return self._attrs["value"]

    def inner_text(self, **kw):
        return self._attrs.get("text", "")

    def is_enabled(self):
        return self._enabled

    def get_attribute(self, name):
        return self._attrs.get(name)


class _Step:
    """One wizard screen: the selectors that exist on it, plus its body text."""

    def __init__(self, selectors, body="", options=()):
        self.selectors = {s: (1, []) for s in selectors}
        self.body = body
        self.options = list(options)


def _flow_steps():
    """The real six-screen flow, keyed by the same constants the driver uses."""
    return [
        _Step([SC._STEP_LANDING, SC._MEDICAL_GET_STARTED[0]],
              "Claims Submission Center Medical Dental Vision Spending Account"),
        _Step([SC._STEP_CLAIM_TYPE, SC._CLAIM_TYPE_NEXT[0]],
              f"I want to submit a medical claim for {SC._DOCTOR_OPTION}"),
        _Step([SC._STEP_PATIENT, SC._PATIENT_TRIGGER[0], SC._PATIENT_NEXT[0]],
              "Submit a Medical Claim Patient name", options=OPTIONS),
        # Every ai-flow screen renders the whole sub-step rail, which is exactly
        # why body text cannot gate these steps.
        _Step([SC._STEP_UPLOAD, SC._UPLOAD_NEXT[0], 'input[type="file"]'],
              "Upload files Processing files Claim details Additional information"),
        _Step([SC._STEP_PROCESSING, SC._PROCESSING_CONTINUE[0]],
              "Upload files Processing files Claim details Additional information"),
        _Step([SC._STEP_CLAIM_DETAILS],
              "Upload files Processing files Claim details Here's what we found"),
    ]


class _FakePage:
    """Replays a scripted sequence of wizard steps.

    A click on a navigation control advances to the next step, which is what
    makes step ordering assertable.
    """

    url = "https://membersecure.anthem.com/member/claims/submission/questionnaire"

    def __init__(self, steps, next_enabled_after=0, closed=True,
                 patient_selection_sticks=True, selection_renders_as_text=False):
        self.steps = steps
        self.i = 0
        self.log = []
        self.next_enabled_after = next_enabled_after
        self.polls = 0
        self.closed = closed
        self.patient_selection_sticks = patient_selection_sticks
        # Anthem's real combobox is an <input>: the chosen name lands in its
        # value and never appears in the page body. The flag models the other
        # kind of widget, one that renders its selection as text.
        self.selection_renders_as_text = selection_renders_as_text
        self.selected = ""

    @property
    def step(self):
        return self.steps[self.i]

    def advance(self):
        self.i = min(self.i + 1, len(self.steps) - 1)

    def _select(self, option):
        if self.patient_selection_sticks:
            self.selected = option

    def inner_text(self, _sel):
        body = self.step.body
        if self.selection_renders_as_text:
            return f"{body} {self.selected}".strip()
        return body

    def locator(self, sel):
        count, texts = self.step.selectors.get(sel, (0, []))
        attrs = {}
        if sel in SC._PATIENT_TRIGGER:
            # The combobox is an <input>; the selection lives in its value.
            attrs = {"value": self.selected}
        return _FakeLocator(self, sel, count=count, texts=texts, attrs=attrs,
                            enabled=self.polls >= self.next_enabled_after)

    def get_by_role(self, role, name=None, **kw):
        if role == "option":
            opts = self.step.options
            if name is not None:
                hit = [o for o in opts if o == name]
                return _FakeLocator(self, name, count=len(hit),
                                    on_click=lambda: self._select(name))
            return _FakeLocator(self, "option", count=len(opts), texts=opts)
        if role == "radio":
            return _FakeLocator(self, name or role, attrs={"aria-checked": "true"})
        return _FakeLocator(self, name or role)

    def get_by_text(self, text, **kw):
        return _FakeLocator(self, text, on_click=lambda: self._select(text))

    def wait_for_timeout(self, _ms):
        self.polls += 1

    def wait_for_event(self, _event, **kw):
        if not self.closed:
            raise TimeoutError("window never closed")
        self.log.append(("wait_for_close", None))

    def screenshot(self, **kw):
        pass


PDF = "/tmp/claim.pdf"


def _happy_page(**kw):
    return _FakePage(_flow_steps(), **kw)


def _clicks(page):
    return [name for action, name in page.log if action == "click"]


# ── Selector contract ────────────────────────────────────────────────────────

def test_step_selectors_are_the_ones_anthem_serves():
    """Literal pin of every selector verified against the live site on
    2026-08-26.

    The flow tests below build their fake steps *from* these constants, so they
    move in lockstep with any edit and cannot notice a wrong value. This test is
    what makes a typo or a half-finished rename fail. Selector correctness
    itself is only ever provable by a live run (see automation/probe_claim_wizard.py);
    what is pinned here is what that run found.
    """
    assert SC._MEDICAL_GET_STARTED[0] == (
        '[data-testid="claims.claimSubmissionTypeCard.card-MEDICAL_CLAIMS-button"]')
    assert SC._CLAIM_TYPE_NEXT == [
        '[data-testid="claims.claimsSubmissionFormTypeSelection.next-button"]']
    assert SC._PATIENT_TRIGGER[0] == '[data-testid="claims.patientDetails.patient-dropdown"]'
    assert SC._PATIENT_NEXT == ['[data-testid="claims.patientDetails.next-button"]']
    assert SC._PROCESSING_CONTINUE == ['[data-testid="claims.fileProcessor.continueButton"]']
    assert SC._UPLOAD_NEXT == ['[data-testid="stepNavigationButtons-continue-button"]']
    assert SC._STEP_LANDING == '[data-testid="claims.claimSubmissionTypes.card-list"]'
    assert SC._STEP_CLAIM_TYPE == (
        '[data-testid="claims.claimsSubmissionFormTypeSelection.options-card"]')
    assert SC._STEP_PATIENT == '[data-testid="claims.patientDetails.patient-dropdown"]'
    assert SC._STEP_UPLOAD == '[data-testid="documentUpload-document-documentUpload-dropZone"]'
    assert SC._STEP_PROCESSING == '[data-testid="claims.fileProcessor.continueButton"]'
    assert SC._STEP_CLAIM_DETAILS == '[data-testid="groupRenderer-claimDetailsFound.title"]'


def test_questionnaire_url_is_the_post_redesign_path():
    """The old /claims/submission-questionnaire path is gone; the live flow
    serves /claims/submission/questionnaire."""
    assert SC.QUESTIONNAIRE_URL.endswith("/member/claims/submission/questionnaire")


# ── fill_wizard ──────────────────────────────────────────────────────────────

def test_happy_path_action_sequence():
    page = _happy_page()
    submit_claim.fill_wizard(page, "Diego", PDF)
    assert page.log == [
        ("click", SC._MEDICAL_GET_STARTED[0]),
        ("click", SC._DOCTOR_OPTION),          # radio
        ("click", SC._CLAIM_TYPE_NEXT[0]),
        ("click", SC._PATIENT_TRIGGER[0]),     # open the dropdown
        ("click", DIEGO),                      # pick the option
        ("click", SC._PATIENT_NEXT[0]),
        ("upload", PDF),
        ("click", SC._UPLOAD_NEXT[0]),
        ("click", SC._PROCESSING_CONTINUE[0]),
        ("wait_for_close", None),
    ]


def test_reaches_the_claim_details_handoff():
    page = _happy_page()
    submit_claim.fill_wizard(page, "Diego", PDF)
    assert SC._STEP_CLAIM_DETAILS in page.step.selectors


def test_ambiguous_patient_stops_before_uploading():
    """The 'never guess a patient' contract: no draft is created."""
    steps = _flow_steps()
    twin = "DIEGO B SMITH"
    steps[2].options = [DIEGO, twin]
    page = _FakePage(steps)
    with pytest.raises(submit_claim.AmbiguousPatientError):
        submit_claim.fill_wizard(page, "Diego", PDF)
    assert ("upload", PDF) not in page.log
    assert SC._PATIENT_NEXT[0] not in _clicks(page)


def test_unknown_patient_stops_before_uploading():
    page = _happy_page()
    with pytest.raises(submit_claim.AmbiguousPatientError):
        submit_claim.fill_wizard(page, "Jordan", PDF)
    assert ("upload", PDF) not in page.log


def test_dry_run_stops_before_the_upload_step():
    """The upload is what creates Anthem's draft, so a dry run must stop above it."""
    page = _happy_page()
    submit_claim.fill_wizard(page, "Diego", PDF, dry_run=True)
    assert ("click", DIEGO) in page.log
    assert ("upload", PDF) not in page.log
    assert SC._PATIENT_NEXT[0] not in _clicks(page)


def test_medical_card_is_clicked_by_testid_not_generic_text():
    """Four cards carry an identical 'Get Started' control; only the Medical
    one may be clicked."""
    page = _happy_page()
    submit_claim.fill_wizard(page, "Diego", PDF)
    assert _clicks(page)[0] == SC._MEDICAL_GET_STARTED[0]
    assert "MEDICAL_CLAIMS" in SC._MEDICAL_GET_STARTED[0]


def test_patient_selection_that_does_not_take_effect_raises():
    # The click lands on nothing, so the combobox value stays empty.
    page = _happy_page(patient_selection_sticks=False)
    with pytest.raises(RuntimeError, match="did not take effect"):
        submit_claim.fill_wizard(page, "Diego", PDF)


def test_patient_selection_is_confirmed_from_the_input_value():
    """Regression: the chosen name goes into the combobox's value and never
    into the page body, so a body-text check calls every successful selection
    a failure. Verified live on 2026-08-26."""
    page = _happy_page()                      # body never contains the name
    submit_claim.fill_wizard(page, "Diego", PDF)
    assert page.selected == DIEGO
    assert DIEGO not in page.inner_text("body")


def test_patient_selection_also_accepts_a_widget_that_renders_text():
    page = _happy_page(selection_renders_as_text=True)
    submit_claim.fill_wizard(page, "Diego", PDF)
    assert ("click", DIEGO) in page.log


def test_does_not_skip_the_processing_step_on_shared_rail_text():
    """Regression: every ai-flow screen lists 'Claim details' in its progress
    rail, so a body-text gate would sail past Processing."""
    steps = _flow_steps()
    page = _FakePage(steps)
    submit_claim.fill_wizard(page, "Diego", PDF)
    assert SC._PROCESSING_CONTINUE[0] in _clicks(page)


# ── draft blocking ───────────────────────────────────────────────────────────

def test_draft_block_raises_immediately_instead_of_timing_out():
    """Anthem diverts the wizard to its draft list when an unfinished draft
    exists; that must be reported, not waited out."""
    steps = _flow_steps()
    steps[2] = _Step([], "You must continue or delete your draft submissions "
                         "before you can submit a new claim Draft submission")
    page = _FakePage(steps)
    with pytest.raises(submit_claim.DraftSubmissionBlockedError, match="Continue that draft"):
        submit_claim.fill_wizard(page, "Diego", PDF)
    assert ("upload", PDF) not in page.log


def test_draft_block_detected_while_waiting_for_any_step():
    page = _FakePage([_Step([], "You must continue or delete your draft submissions first")])
    with pytest.raises(submit_claim.DraftSubmissionBlockedError):
        submit_claim._wait_for_step(page, SC._STEP_PATIENT, "the patient page",
                                    timeout_ms=60_000, poll_ms=1, clock=lambda: 0.0)


def test_wait_for_step_times_out_naming_the_script():
    page = _FakePage([_Step([], "nothing useful here")])
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError, match="submit_claim.py"):
        submit_claim._wait_for_step(page, SC._STEP_LANDING, "the landing page",
                                    timeout_ms=1_000, poll_ms=1,
                                    clock=lambda: next(ticks))


def test_wait_for_step_returns_once_the_selector_exists():
    page = _FakePage([_Step([SC._STEP_UPLOAD], "Upload files")])
    submit_claim._wait_for_step(page, SC._STEP_UPLOAD, "the upload page",
                                timeout_ms=1_000, poll_ms=1, clock=lambda: 0.0)


# ── wait_for_processing_done ─────────────────────────────────────────────────

def _processing_page(**kw):
    return _FakePage([_Step([SC._STEP_PROCESSING, SC._PROCESSING_CONTINUE[0]],
                            "Processing files")], **kw)


def test_wait_for_processing_done_returns_once_continue_is_enabled():
    page = _processing_page(next_enabled_after=2)
    assert submit_claim.wait_for_processing_done(
        page, timeout_ms=60_000, poll_ms=1, clock=lambda: 0.0) is True
    assert page.polls >= 2


def test_wait_for_processing_done_treats_aria_disabled_as_disabled():
    """is_enabled() is True but aria-disabled says otherwise — the likeliest
    real-world defect, since Playwright only knows the native attribute."""
    class _AriaPage(_FakePage):
        def locator(self, sel):
            if sel == SC._PROCESSING_CONTINUE[0]:
                return _FakeLocator(self, "Continue", enabled=True,
                                    attrs={"aria-disabled": "true"})
            return super().locator(sel)

    page = _AriaPage([_Step([SC._STEP_PROCESSING], "Processing files")])
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError, match="never became enabled"):
        submit_claim.wait_for_processing_done(page, timeout_ms=1_000, poll_ms=1,
                                              clock=lambda: next(ticks))


def test_wait_for_processing_done_treats_disabled_class_as_disabled():
    class _ClassPage(_FakePage):
        def locator(self, sel):
            if sel == SC._PROCESSING_CONTINUE[0]:
                return _FakeLocator(self, "Continue", enabled=True,
                                    attrs={"class": "btn btn-primary disabled"})
            return super().locator(sel)

    page = _ClassPage([_Step([SC._STEP_PROCESSING], "Processing files")])
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError, match="never became enabled"):
        submit_claim.wait_for_processing_done(page, timeout_ms=1_000, poll_ms=1,
                                              clock=lambda: next(ticks))


def test_wait_for_processing_done_detects_auto_advance():
    """If the wizard reached Claim details on its own, clicking Continue again
    would skip a step."""
    page = _FakePage([_Step([SC._STEP_CLAIM_DETAILS], "Claim details")])
    assert submit_claim.wait_for_processing_done(
        page, timeout_ms=1_000, poll_ms=1, clock=lambda: 0.0) is False


@pytest.mark.parametrize("banner", ["could not be processed", "upload failed",
                                    "unsupported file"])
def test_wait_for_processing_done_raises_on_rejection_banner(banner):
    page = _FakePage([_Step([SC._STEP_PROCESSING], f"Processing files {banner}")])
    with pytest.raises(RuntimeError, match="rejected the uploaded PDF"):
        submit_claim.wait_for_processing_done(page, timeout_ms=1_000, poll_ms=1,
                                              clock=lambda: 0.0)


def test_wait_for_processing_done_times_out_naming_the_constant():
    page = _processing_page(next_enabled_after=10_000)
    ticks = iter(range(0, 1000))
    with pytest.raises(RuntimeError, match="_PROCESSING_CONTINUE"):
        submit_claim.wait_for_processing_done(page, timeout_ms=1_000, poll_ms=1,
                                              clock=lambda: next(ticks))
