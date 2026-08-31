"""
File an out-of-network medical claim with Anthem.

Drives Anthem's claim wizard as far as the upload step: Medical → "Doctor or
other medical specialist" → patient → upload the PDF → wait out Anthem's file
processing. Then STOPS on the "Claim details" step and hands the browser to the
user, who checks the extracted data, completes the remaining steps and clicks
Submit. Nothing is ever filed without a human.

Stopping there is not just caution about filing. "Claim details" is where
Anthem shows what *its* extraction read off the PDF ("Here's what we found in
your claim") — provider NPI, tax ID, diagnosis and procedure codes, amounts.
That page ships with errors (a 9-digit provider ZIP flagged as invalid on the
run this was written against), and every field feeds a real reimbursement
claim, so a human reviews it.

Inputs come from env vars (set by backend/app/automation.py:run_claim_filing):
    CLAIM_SUBMISSION_ID (logging only), CLAIM_MEMBER, CLAIM_PDF_PATH
    CLAIM_DRY_RUN=1 stops before the upload step — uploading is what makes
    Anthem save a draft, so everything above it stays repeatable against the
    real site with no side effects.

Usage (manual):
    CLAIM_MEMBER="Nolan" CLAIM_PDF_PATH=/tmp/claim.pdf \
        python automation/submit_claim.py
"""
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.sync_api import Page, sync_playwright

import auth

QUESTIONNAIRE_URL = "https://membersecure.anthem.com/member/claims/submission/questionnaire"

# Hold the window open for the user to finish Claim details → Additional
# information → Reimbursement → Submit. Sized (with the login
# wait and the processing poll) below _FILING_TIMEOUT_S in
# backend/app/automation.py so we exit cleanly rather than being killed.
_HANDOFF_TIMEOUT_MS = 900_000  # 15 min
# A failed run leaves the window open so the user can see what happened and
# finish by hand — but only briefly. Reusing the 15-minute handoff hold here
# turned a 60-second auth error into a 16-minute silent hang.
_ERROR_REVIEW_TIMEOUT_MS = 180_000  # 3 min
# The questionnaire page must actually render. Generous because auth.login can
# return early on an expired-but-cookied session — this is where the user gets
# time to sign in in the open window.
_READY_TIMEOUT_MS = 240_000
# Anthem scans/OCRs the upload on "Processing files" before enabling Continue.
_PROCESSING_TIMEOUT_MS = 180_000

# ── Selectors ────────────────────────────────────────────────────────────────
# Anthem's claims flow is a react-native-web micro-app: its controls are <div>s
# carrying a role and a data-testid — never <button> or <a>. Tag-based selectors
# ('button:has-text(...)') and get_by_role("button") therefore match nothing,
# which is exactly how the pre-2026-08 version of this file broke: the text was
# on the page, but nothing clickable held it.
#
# Prefer data-testid. The css-*/r-* class names are generated per build and are
# never usable. Text/aria fallbacks sit one layer down so a renamed testid
# degrades instead of failing outright.

_MEDICAL_GET_STARTED = [
    '[data-testid="claims.claimSubmissionTypeCard.card-MEDICAL_CLAIMS-button"]',
    '[aria-label="Get Started with Medical"]',
    # Legacy markup, kept in case Anthem rolls back.
    '[class*="card"]:has-text("Medical") button:has-text("Get Started")',
]
_DOCTOR_OPTION = "Doctor or other medical specialist"
_CLAIM_TYPE_NEXT = ['[data-testid="claims.claimsSubmissionFormTypeSelection.next-button"]']
_PATIENT_TRIGGER = [
    '[data-testid="claims.patientDetails.patient-dropdown"]',
    '[role="combobox"][aria-label*="Patient name" i]',
    '[role="combobox"]',
]
_PATIENT_NEXT = ['[data-testid="claims.patientDetails.next-button"]']
_UPLOAD_DROPZONE_BUTTON = [
    '[data-testid="documentUpload-document-documentUpload-dropZone-select-button"]',
]
_UPLOAD_NEXT = ['[data-testid="stepNavigationButtons-continue-button"]']
_PROCESSING_CONTINUE = ['[data-testid="claims.fileProcessor.continueButton"]']
_NEXT_BUTTON = ["Next", "Continue"]
_UPLOAD_BUTTON = ["Select document(s) to upload", "Select Document(s) to Upload", "Upload"]

# Step gates. Each is a selector that exists ONLY on its own step.
#
# Body text cannot gate these steps: every ai-flow page renders the full
# sub-step list ("Upload files … Processing files … Claim details …") in its
# progress rail, so waiting for the text "Claim details" returns true while
# still sitting on Processing — the same skip-a-step failure the old five-page
# "Step N of 5" needles were written to prevent.
_STEP_LANDING = '[data-testid="claims.claimSubmissionTypes.card-list"]'
_STEP_CLAIM_TYPE = '[data-testid="claims.claimsSubmissionFormTypeSelection.options-card"]'
_STEP_PATIENT = '[data-testid="claims.patientDetails.patient-dropdown"]'
_STEP_UPLOAD = '[data-testid="documentUpload-document-documentUpload-dropZone"]'
_STEP_PROCESSING = '[data-testid="claims.fileProcessor.continueButton"]'
_STEP_CLAIM_DETAILS = '[data-testid="groupRenderer-claimDetailsFound.title"]'

# Banner text that means Anthem rejected the upload outright — fail fast rather
# than polling for the full processing timeout.
_UPLOAD_REJECTED = ("could not be processed", "upload failed", "unsupported file")

# Anthem refuses to start a new claim while an unfinished draft exists and
# diverts the wizard to the draft list. Every abandoned run leaves one behind,
# so this is a routine state, not an exotic one — detect it and say so rather
# than timing out on whichever page we were expecting.
_DRAFT_BLOCK = "continue or delete your draft submissions"


class AmbiguousPatientError(RuntimeError):
    """Zero or 2+ dropdown options matched the member — refuse to guess."""


class DraftSubmissionBlockedError(RuntimeError):
    """An unfinished draft in Anthem is blocking any new claim."""


# ── Patient matching (pure, unit-tested) ─────────────────────────────────────

_DOB_SUFFIX = re.compile(r"\s*\(\s*\d{1,2}/\d{1,2}/\d{4}\s*\)\s*$")
_PLACEHOLDER = re.compile(r"^\s*(select a patient|select|choose|--)", re.I)


def _normalize_name(raw: str) -> tuple[str, str]:
    """"JOHN G O'LEARY (01/19/1981)" -> ("john", "oleary").

    Strips the trailing (DOB), lowercases, drops punctuation so O'LEARY and
    OLeary agree, and removes middle initials (single-letter interior tokens).
    Returns (first, last); last is "" for single-token names like "Newborn".
    """
    s = _DOB_SUFFIX.sub("", raw or "").strip()
    s = re.sub(r"[^a-z0-9 ]", "", s.lower())
    parts = [p for p in s.split() if p]
    if len(parts) >= 3:
        parts = [parts[0]] + [p for p in parts[1:-1] if len(p) > 1] + [parts[-1]]
    if not parts:
        return "", ""
    return parts[0], (parts[-1] if len(parts) > 1 else "")


def match_patient_options(options: list[str], member: str) -> list[str]:
    """Dropdown options matching the submission's member_name.

    Compares first names always, and surnames only when BOTH sides have one —
    submissions store either "Nolan" or "Nolan O'Leary", and the "Newborn"
    option has no surname at all. Returns every hit; the caller refuses to act
    unless there is exactly one.
    """
    m_first, m_last = _normalize_name(member)
    if not m_first:
        return []
    hits = []
    for opt in options:
        if _PLACEHOLDER.match(opt or ""):
            continue
        o_first, o_last = _normalize_name(opt)
        if o_first != m_first:
            continue
        if m_last and o_last and m_last != o_last:
            continue
        hits.append(opt)
    return hits


def _one_match(options: list[str], member: str) -> str:
    hits = match_patient_options(options, member)
    if len(hits) == 1:
        return hits[0]
    raise AmbiguousPatientError(
        f"Could not pick the patient for member {member!r}: "
        f"{len(hits)} of {len(options)} options matched ({hits or 'none'}). "
        f"Options offered: {options}. "
        "Choose the patient in the open browser window and continue there."
    )


# ── Page helpers ─────────────────────────────────────────────────────────────

def _wait_for_close(page: Page, timeout_ms: int = _HANDOFF_TIMEOUT_MS) -> None:
    """Block until the user closes the window (or the hold elapses)."""
    try:
        page.wait_for_event("close", timeout=timeout_ms)
    except Exception:
        pass


def _save_error_screenshot(page: Page) -> None:
    try:
        path = Path(__file__).parent.parent / "data" / "claim_filing_last_error.png"
        page.screenshot(path=str(path))
        print(f"Saved screenshot to {path}")
    except Exception:
        pass


def _body_text(page: Page) -> str:
    try:
        return (page.inner_text("body") or "").lower()
    except Exception:
        return ""


def _raise_if_draft_blocked(body: str) -> None:
    """Anthem parks the wizard on the draft list instead of the page we wanted."""
    if _DRAFT_BLOCK in body:
        raise DraftSubmissionBlockedError(
            "Anthem has an unfinished draft submission and won't start a new claim "
            "until it's dealt with. Open the Claim Submission Center in the browser "
            "window and either Continue that draft (to finish it) or Delete it, then "
            "run this again."
        )


def _wait_for_step(page: Page, selector: str, what: str, timeout_ms: int = 30_000,
                   poll_ms: int = 500, clock=time.monotonic) -> None:
    """Block until `selector` — a control unique to one wizard step — exists.

    The selector form of _wait_for_page, and the right gate for the ai-flow
    steps, whose body text is not step-specific. Draft-blocking is still checked
    on every poll: Anthem answers a blocked claim by diverting to the draft list,
    where the step we are waiting for will simply never appear.
    """
    deadline = clock() + timeout_ms / 1000
    while True:
        try:
            if page.locator(selector).count() > 0:
                return
        except Exception:
            pass
        _raise_if_draft_blocked(_body_text(page))
        if clock() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for {what} (looking for {selector}) after "
                f"{timeout_ms // 1000}s. Current URL: {page.url}. "
                "Update submit_claim.py if Anthem changed their wizard."
            )
        page.wait_for_timeout(poll_ms)


def _click_text(page: Page, texts: list[str], name: str) -> None:
    for t in texts:
        try:
            page.get_by_text(t, exact=False).first.click(timeout=10_000)
            return
        except Exception:
            continue
    raise RuntimeError(
        f"Could not find {name}.\n"
        f"Texts tried: {texts}\n"
        f"Update submit_claim.py if Anthem changed their wizard."
    )


def _click_button(page: Page, names: list[str], what: str) -> None:
    """Click a wizard button. Prefers the button role, falling back to text so
    it tolerates minor markup differences."""
    for n in names:
        try:
            page.get_by_role("button", name=n, exact=False).first.click(timeout=8_000)
            return
        except Exception:
            continue
    _click_text(page, names, what)


def _click_selector(page: Page, selectors: list[str], what: str,
                    fallback_texts: list[str] | None = None) -> None:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.click(timeout=8_000)
            return
        except Exception:
            continue
    if fallback_texts:
        _click_button(page, fallback_texts, what)
        return
    raise RuntimeError(
        f"Could not find {what}.\n"
        f"Selectors tried: {selectors}\n"
        f"Update submit_claim.py if Anthem changed their wizard."
    )


def _check_radio(page: Page, label: str, what: str) -> None:
    """Select a radio option.

    Anthem's radios are <div role="radio" aria-label="..."> with no <input>
    behind them, so a plain click is the reliable action; check() is kept as a
    fallback for a native control.
    """
    radio = page.get_by_role("radio", name=label, exact=False).first
    try:
        radio.click(timeout=8_000)
        if (radio.get_attribute("aria-checked") or "true").lower() != "false":
            return
    except Exception:
        pass
    try:
        radio.check(timeout=8_000)
        return
    except Exception:
        pass
    _click_text(page, [label], what)


def _upload_document(page: Page, pdf_path: str) -> None:
    """Attach the PDF. Sets the hidden file input directly (no native dialog);
    falls back to the file chooser."""
    try:
        page.locator('input[type="file"]').first.set_input_files(pdf_path, timeout=10_000)
        return
    except Exception:
        pass
    with page.expect_file_chooser(timeout=15_000) as fc:
        _click_selector(page, _UPLOAD_DROPZONE_BUTTON, "the upload button",
                        fallback_texts=_UPLOAD_BUTTON)
    fc.value.set_files(pdf_path)


def _is_enabled(btn) -> bool:
    """Playwright's is_enabled() only understands the native `disabled`
    attribute; this wizard's Next may be greyed out via aria-disabled or a
    class instead."""
    try:
        if not btn.is_enabled():
            return False
        if (btn.get_attribute("aria-disabled") or "").lower() == "true":
            return False
        if btn.get_attribute("disabled") is not None:
            return False
        return "disabled" not in (btn.get_attribute("class") or "").lower()
    except Exception:
        return False


def wait_for_processing_done(page: Page, timeout_ms: int = _PROCESSING_TIMEOUT_MS,
                             poll_ms: int = 1_000, clock=time.monotonic) -> bool:
    """Poll the "Processing files" step until Anthem finishes scanning the PDF.

    Returns True if Continue became clickable and the caller should click it,
    False if the wizard advanced to "Claim details" on its own — in which case
    clicking Continue again would skip a step. Raises if Anthem rejected the
    upload, or on timeout.
    """
    deadline = clock() + timeout_ms / 1000
    while True:
        if page.locator(_STEP_CLAIM_DETAILS).count() > 0:
            print("Wizard auto-advanced past processing.")
            return False
        body = _body_text(page)
        for bad in _UPLOAD_REJECTED:
            if bad in body:
                raise RuntimeError(
                    f"Anthem rejected the uploaded PDF ({bad!r}). "
                    "Check the file in the open browser window."
                )
        # Re-resolve each poll: the button node is replaced when processing ends.
        btn = page.locator(_PROCESSING_CONTINUE[0]).last
        if btn.count() and _is_enabled(btn):
            return True
        if clock() >= deadline:
            raise RuntimeError(
                "Continue never became enabled on the 'Processing files' step after "
                f"{timeout_ms // 1000}s. Anthem may still be scanning the PDF, or the "
                "button markup changed — update _PROCESSING_CONTINUE in submit_claim.py."
            )
        page.wait_for_timeout(poll_ms)


def _select_patient(page: Page, member: str) -> str:
    """Pick the patient from the "Patient name" dropdown.

    The control is a role=combobox that opens a role=option list; there is no
    native <select> behind it, so the options have to be read from the open
    menu. Options are plain names ("NOLAN F O'LEARY") — Anthem dropped the
    trailing (DOB) that used to disambiguate them, so identical first names in
    one household are now distinguishable only by surname. That is precisely
    why _one_match refuses to act on anything but a single hit.
    """
    _click_selector(page, _PATIENT_TRIGGER, "the Patient name dropdown")
    page.wait_for_timeout(750)

    opts = page.get_by_role("option")
    if opts.count() == 0:
        opts = page.locator('[role="option"], li[class*="option"], li[role="menuitem"]')
    options = [t.strip() for t in opts.all_text_contents()]
    chosen = _one_match(options, member)

    # Click the option element itself rather than its text: the chosen name also
    # renders in the combobox once selected, so a text click can hit the wrong node.
    try:
        page.get_by_role("option", name=chosen, exact=True).first.click(timeout=8_000)
    except Exception:
        page.get_by_text(chosen, exact=True).first.click(timeout=8_000)

    print(f"Selected patient: {chosen}")

    if not _selection_took(page, chosen):
        raise RuntimeError(
            f"Patient selection did not take effect (expected {chosen!r} in the "
            "Patient name field). Pick the patient in the open browser window."
        )
    return chosen


def _control_value(page: Page, selectors: list[str]) -> str:
    """The current value of a form control, whichever way it stores one."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
        except Exception:
            continue
        for read in (lambda: loc.input_value(timeout=2_000),
                     lambda: loc.get_attribute("value"),
                     lambda: loc.inner_text()):
            try:
                value = read()
            except Exception:
                continue
            if value:
                return value
    return ""


def _selection_took(page: Page, chosen: str) -> bool:
    """Confirm the patient click landed — a click that hits nothing is silent.

    The chosen name goes into the combobox's `value`, and inner_text() never
    returns input values, so checking the page body reports every successful
    selection as a failure. Read the control itself, and fall back to the body
    for a widget that renders its selection as text.
    """
    first, _ = _normalize_name(chosen)
    if not first:
        return True
    haystacks = (_control_value(page, _PATIENT_TRIGGER), _body_text(page))
    return any(
        first in re.sub(r"[^a-z0-9 ]", "", (h or "").lower()) for h in haystacks
    )


# ── The wizard ───────────────────────────────────────────────────────────────

def fill_wizard(page: Page, member: str, pdf_path: str, dry_run: bool = False) -> None:
    # 0. The Claims Submission Center must actually render. auth.login can
    #    return a false positive on an expired-but-cookied session — this gate
    #    is where the user signs in if that happens.
    _wait_for_step(page, _STEP_LANDING, "the Claims Submission Center",
                   timeout_ms=_READY_TIMEOUT_MS)

    # 1. Medical → Get Started. Four cards (Medical, Dental, Vision, Spending
    #    Account) carry an identical control, so this must stay scoped to the
    #    Medical card rather than taking the first match.
    _click_selector(page, _MEDICAL_GET_STARTED, "Get Started under Medical")

    # 2. "I want to submit a medical claim for" → Doctor or other medical specialist
    _wait_for_step(page, _STEP_CLAIM_TYPE, "the claim-type page")
    _check_radio(page, _DOCTOR_OPTION, f"the {_DOCTOR_OPTION!r} option")
    _click_selector(page, _CLAIM_TYPE_NEXT, "the Next button (claim type)",
                    fallback_texts=_NEXT_BUTTON)

    # 3. Patient name.
    _wait_for_step(page, _STEP_PATIENT, "the patient page")
    _select_patient(page, member)
    if dry_run:
        # Exit immediately rather than holding the window: a dry run exists to
        # iterate on selectors, so it must not block for the handoff period.
        print("CLAIM_DRY_RUN=1 — stopping before the upload. Nothing was filed.")
        return
    _click_selector(page, _PATIENT_NEXT, "the Next button (patient)",
                    fallback_texts=_NEXT_BUTTON)

    # 4. Upload files. This is the step that creates Anthem's draft, so
    #    everything above it is repeatable and everything below it is not.
    _wait_for_step(page, _STEP_UPLOAD, "the upload page")
    _upload_document(page, pdf_path)
    print("Uploaded the claim PDF.")
    _click_selector(page, _UPLOAD_NEXT, "the Next button (upload)",
                    fallback_texts=_NEXT_BUTTON)

    # 5. Processing files: Continue starts disabled while Anthem scans the PDF.
    _wait_for_step(page, _STEP_PROCESSING, "the processing page")
    print("Waiting for Anthem to finish processing the upload…")
    if wait_for_processing_done(page):
        _click_selector(page, _PROCESSING_CONTINUE, "the Continue button (processing)",
                        fallback_texts=_NEXT_BUTTON)

    # 6. Handoff on "Claim details" — see the module docstring for why this is
    #    the stopping point and not merely a convenient one.
    _wait_for_step(page, _STEP_CLAIM_DETAILS, "the Claim details step")
    print(
        "Anthem's wizard is on 'Claim details'. Check the information Anthem "
        "extracted from the PDF — provider NPI, tax ID, ZIP, diagnosis and "
        "procedure codes, amounts — correct anything wrong, then finish the "
        "remaining steps and click Submit in the browser window. Nothing is filed "
        f"until you do. This window closes automatically in "
        f"{_HANDOFF_TIMEOUT_MS // 60_000} minutes; close it yourself when you're done."
    )
    _wait_for_close(page)


def main() -> int:
    submission_id = os.environ.get("CLAIM_SUBMISSION_ID", "")
    member = os.environ.get("CLAIM_MEMBER", "")
    pdf_path = os.environ.get("CLAIM_PDF_PATH", "")
    dry_run = os.environ.get("CLAIM_DRY_RUN") == "1"

    if not pdf_path or not os.path.exists(pdf_path):
        print(f"[input] ERROR: no PDF at {pdf_path!r} — a PDF is required to file a claim.")
        return 1
    if submission_id:
        print(f"Filing submission {submission_id} for member {member!r}.")

    username, password = auth.get_credentials()

    errors: list[str] = []
    with sync_playwright() as pw:
        context = auth.launch_context(pw)
        page = context.new_page()
        try:
            auth.login(page, username, password)
            page.goto(QUESTIONNAIRE_URL, wait_until="domcontentloaded", timeout=60_000)
            auth.check_for_site_error(page)
        except Exception as e:
            print(f"[auth] ERROR: {e}")
            errors.append(f"auth: {e}")
        else:
            try:
                fill_wizard(page, member, pdf_path, dry_run=dry_run)
            except DraftSubmissionBlockedError as e:
                print(f"[draft] ERROR: {e}")
                errors.append(f"draft: {e}")
            except AmbiguousPatientError as e:
                print(f"[patient] ERROR: {e}")
                errors.append(f"patient: {e}")
            except Exception as e:
                print(f"[wizard] ERROR: {e}")
                errors.append(f"wizard: {e}")

        # On failure, don't slam the window shut — capture the page and leave it
        # open so the user can see what happened and finish by hand.
        if errors:
            _save_error_screenshot(page)
            print(
                "Leaving the browser open for "
                f"{_ERROR_REVIEW_TIMEOUT_MS // 60_000} minutes — finish in the window, "
                "or close it to exit now."
            )
            _wait_for_close(page, timeout_ms=_ERROR_REVIEW_TIMEOUT_MS)

        try:
            context.close()
        except Exception:
            pass

    if errors:
        print(f"\nCompleted with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
