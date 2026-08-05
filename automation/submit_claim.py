"""
File an out-of-network medical claim with Anthem.

Drives Anthem's claim wizard as far as the upload step: Medical → "Doctor or
other medical specialist" → patient → requirements → upload the PDF → wait out
Anthem's file processing. Then STOPS at "Step 3 of 5" and hands the browser to
the user, who completes the remaining steps and clicks Submit. Nothing is ever
filed without a human.

Inputs come from env vars (set by backend/app/automation.py:run_claim_filing):
    CLAIM_SUBMISSION_ID (logging only), CLAIM_MEMBER, CLAIM_PDF_PATH
    CLAIM_DRY_RUN=1 stops before "Submit a Claim" — the last point before Anthem
    creates any server-side state, so steps 1-3 stay repeatable against the real
    site with no side effects.

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

QUESTIONNAIRE_URL = "https://membersecure.anthem.com/member/claims/submission-questionnaire"

# Hold the window open for the user to finish steps 3-5. Sized (with the login
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
# Anthem scans/OCRs the upload on "Step 2 of 5" before enabling Next.
_PROCESSING_TIMEOUT_MS = 180_000

# Selectors for the wizard. Update these if Anthem changes their UI.
# Medical, Dental and Vision cards all carry an identical "Get Started" button,
# so scope to the Medical card first; the positional fallback relies on Medical
# being the leftmost card.
_MEDICAL_GET_STARTED = [
    '[class*="card"]:has-text("Medical") button:has-text("Get Started")',
    'div:has-text("Medical") > button:has-text("Get Started")',
    'section:has-text("Medical") a:has-text("Get Started")',
]
_DOCTOR_OPTION = "Doctor or other medical specialist"
_NEXT_BUTTON = ["Next", "Continue"]
_SUBMIT_A_CLAIM = ["Submit a Claim", "Submit Claim"]
_PATIENT_SELECT = ['select[name*="patient" i]', 'select[id*="patient" i]', 'select']
_PATIENT_TRIGGER = [
    '[role="combobox"]',
    'button:has-text("Select a patient")',
    '[class*="dropdown"]:has-text("Select a patient")',
]
_UPLOAD_BUTTON = ["Select Document(s) to Upload", "Select Documents to Upload", "Upload"]

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


def _wait_for_page(page: Page, needle: str, what: str, timeout_ms: int = 30_000,
                   poll_ms: int = 500, clock=time.monotonic) -> None:
    """Block until `needle` appears in the page body.

    Every wizard step is gated on its own heading. Four of these pages carry a
    "Next" button, so acting before the SPA has navigated re-clicks the previous
    page's Next and silently skips a step — which then surfaces as an
    inscrutable selector error several steps later.
    """
    deadline = clock() + timeout_ms / 1000
    key = needle.lower()
    while True:
        body = _body_text(page)
        if key in body:
            return
        _raise_if_draft_blocked(body)
        if clock() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for {what} (looking for {needle!r}) after "
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
    try:
        page.get_by_role("radio", name=label, exact=False).first.check(timeout=8_000)
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
        _click_button(page, _UPLOAD_BUTTON, "the upload button")
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


def wait_for_next_enabled(page: Page, timeout_ms: int = _PROCESSING_TIMEOUT_MS,
                          poll_ms: int = 1_000, clock=time.monotonic) -> bool:
    """Poll until the Processing page's Next button becomes clickable.

    Returns False if the wizard auto-advanced past processing on its own, in
    which case the caller must NOT click Next again. Raises if Anthem rejected
    the upload, or on timeout.
    """
    deadline = clock() + timeout_ms / 1000
    while True:
        body = _body_text(page)
        if "step 3 of 5" in body:
            print("Wizard auto-advanced past processing.")
            return False
        for bad in _UPLOAD_REJECTED:
            if bad in body:
                raise RuntimeError(
                    f"Anthem rejected the uploaded PDF ({bad!r}). "
                    "Check the file in the open browser window."
                )
        # Re-resolve each poll: the button node is replaced when processing ends.
        btn = page.get_by_role("button", name="Next", exact=False).last
        if btn.count() and _is_enabled(btn):
            return True
        if clock() >= deadline:
            raise RuntimeError(
                "Next never became enabled on 'Step 2 of 5 - Processing File(s)' after "
                f"{timeout_ms // 1000}s. Anthem may still be scanning the PDF, or the "
                "button markup changed — update submit_claim.py."
            )
        page.wait_for_timeout(poll_ms)


def _select_patient(page: Page, member: str) -> str:
    """Pick the patient from the Patient Name dropdown.

    Handles a native <select> and an ARIA combobox; only the option-reading
    differs, the matching decision is identical.
    """
    chosen = ""
    # Branch A: native <select>.
    for sel in _PATIENT_SELECT:
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                continue
            options = [t.strip() for t in el.locator("option").all_text_contents()]
            if not any(_DOB_SUFFIX.search(o) for o in options):
                continue  # not the patient select
            chosen = _one_match(options, member)
            el.select_option(label=chosen, timeout=10_000)
            break
        except AmbiguousPatientError:
            raise
        except Exception:
            continue

    # Branch B: custom widget.
    if not chosen:
        _click_selector(page, _PATIENT_TRIGGER, "the Patient Name dropdown")
        page.wait_for_timeout(500)
        opts = page.get_by_role("option")
        if opts.count() == 0:
            opts = page.locator('[role="option"], li[class*="option"], li[role="menuitem"]')
        options = [t.strip() for t in opts.all_text_contents()]
        chosen = _one_match(options, member)
        page.get_by_text(chosen, exact=True).first.click(timeout=8_000)

    print(f"Selected patient: {chosen}")

    # A click that lands on nothing is otherwise silent — confirm it took.
    first, _ = _normalize_name(chosen)
    if first and first not in re.sub(r"[^a-z0-9 ]", "", _body_text(page)):
        raise RuntimeError(
            f"Patient selection did not take effect (expected {chosen!r} to appear "
            "on the page). Pick the patient in the open browser window."
        )
    return chosen


# ── The wizard ───────────────────────────────────────────────────────────────

def fill_wizard(page: Page, member: str, pdf_path: str, dry_run: bool = False) -> None:
    # 0. The questionnaire page must actually render. auth.login decides "already
    #    logged in" from a URL snapshot, which can be a false positive on an
    #    expired session — this gate is where the user signs in if that happens.
    _wait_for_page(page, "Get Started", "the Claim Submission Center",
                   timeout_ms=_READY_TIMEOUT_MS)

    # 1. Medical → Get Started
    _click_selector(page, _MEDICAL_GET_STARTED, "Get Started under Medical",
                    fallback_texts=["Get Started"])

    # 2. "I want to submit a medical claim for" → Doctor or other medical specialist
    _wait_for_page(page, "I want to submit a medical claim for", "the claim-type page")
    _check_radio(page, _DOCTOR_OPTION, f"the {_DOCTOR_OPTION!r} option")
    _click_button(page, _NEXT_BUTTON, "the Next button (claim type)")

    # 3. Patient Name → Submit a Claim
    _wait_for_page(page, "Patient Name", "the Patient Name page")
    _select_patient(page, member)
    if dry_run:
        # Exit immediately rather than holding the window: a dry run exists to
        # iterate on selectors, so it must not block for the handoff period.
        print("CLAIM_DRY_RUN=1 — stopping before 'Submit a Claim'. Nothing was filed.")
        return
    _click_button(page, _SUBMIT_A_CLAIM, "the Submit a Claim button")

    # 4. Claim Submission Requirements → Next
    _wait_for_page(page, "Claim Submission Requirements", "the requirements page")
    _click_button(page, _NEXT_BUTTON, "the Next button (requirements)")

    # 5. Step 1 of 5 — Upload Your File(s)
    _wait_for_page(page, "Upload Your File", "the upload page")
    _upload_document(page, pdf_path)
    print("Uploaded the claim PDF.")
    _click_button(page, _NEXT_BUTTON, "the Next button (upload)")

    # 6. Step 2 of 5 — Processing File(s): Next starts disabled.
    _wait_for_page(page, "Processing File", "the processing page")
    print("Waiting for Anthem to finish processing the upload…")
    if wait_for_next_enabled(page):
        _click_button(page, _NEXT_BUTTON, "the Next button (processing)")

    # 7. Handoff.
    print(
        "Anthem's wizard is at Step 3 of 5. Complete the remaining steps and click "
        "Submit in the browser window — nothing is filed until you do. This window "
        f"closes automatically in {_HANDOFF_TIMEOUT_MS // 60_000} minutes; close it "
        "yourself when you're done."
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
