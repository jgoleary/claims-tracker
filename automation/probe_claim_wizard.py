"""Read-only probe of Anthem's claim-submission wizard.

Diagnostic only: logs in, opens the questionnaire URL, and dumps what the page
actually is — URL, full body text, and every clickable element with its
visibility. Clicks nothing itself, so it cannot create or advance a draft.

Anthem's wizard is driven entirely by text/role selectors, so when a run fails
with "could not find X" the only way to tell a UI redesign from a page we were
never on is to look at the page.

    --follow    Keep the window open and snapshot every page YOU navigate to,
                so the whole wizard can be recorded by hand without the script
                clicking anything. Numbered outputs: probe_wizard_01.*, _02.*…

Outputs land in data/ as .txt (body text + clickable inventory), .html (raw
DOM) and .png (full-page screenshot).

Usage:
    backend/.venv/bin/python automation/probe_claim_wizard.py [--follow]
"""
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.sync_api import Page, sync_playwright

import auth
from submit_claim import QUESTIONNAIRE_URL

DATA = Path(__file__).parent.parent / "data"

# Anthem's claims micro-app is react-native-web: its controls are <div>s with
# role=link/button and a data-testid, never <button>/<a>. Match on role, not tag.
_CLICKABLE = (
    'button, a, summary, input[type="submit"], '
    '[role="button"], [role="link"], [role="tab"], [role="option"], [role="menuitem"], '
    '[role="radio"], [role="checkbox"], [data-testid*="button"], [data-testid*="link"]'
)
_CONTROLS = (
    'select, input, textarea, [role="combobox"], [role="listbox"], [role="radiogroup"]'
)


def _testid_inventory(page: Page) -> list[str]:
    """Every data-testid on the page. These are the stable hooks worth writing
    selectors against — the css-* / r-* class names are generated per build."""
    ids = page.eval_on_selector_all(
        "[data-testid]", "els => els.map(e => e.getAttribute('data-testid'))"
    )
    return ["===== DATA-TESTIDS ====="] + [f"  {t}" for t in sorted(set(ids))]


def _inventory(page: Page, selector: str, label: str) -> list[str]:
    """One line per matching element: visibility, text, and the attributes we
    write selectors against."""
    out = [f"===== {label} ({selector}) ====="]
    loc = page.locator(selector)
    for i in range(loc.count()):
        el = loc.nth(i)
        try:
            text = " ".join((el.inner_text() or "").split())[:120]
            attrs = {
                k: el.get_attribute(k)
                for k in ("id", "name", "class", "type", "aria-label", "href", "role")
            }
            attrs = {k: v[:100] for k, v in attrs.items() if v}
            vis = "VISIBLE" if el.is_visible() else "hidden "
            out.append(f"[{i:>3}] {vis} text={text!r} {attrs}")
        except Exception as e:
            out.append(f"[{i:>3}] <unreadable: {e}>")
    return out


def probe(page: Page, body: str | None = None) -> str:
    lines = [f"URL: {page.url}", f"TITLE: {page.title()}", ""]
    if body is None:
        body = page.inner_text("body") or ""
    lines += ["===== BODY TEXT =====", body, ""]
    lines += _inventory(page, _CLICKABLE, "CLICKABLE") + [""]
    lines += _inventory(page, _CONTROLS, "FORM CONTROLS") + [""]
    lines += _testid_inventory(page) + [""]

    # The needles submit_claim.py gates each wizard step on. Which of these are
    # present decides whether we are on the page we think we are.
    needles = [
        "Get Started", "Medical", "Dental", "Vision", "Spending Account",
        "I want to submit a medical claim for", "Doctor or other medical specialist",
        "Patient name", "Upload files", "Processing files", "Claim details",
        "Additional information", "Reimbursement", "Select", "Update & Submit",
        "continue or delete your draft submissions", "draft",
    ]
    low = body.lower()
    lines.append("===== NEEDLE PRESENCE (case-insensitive) =====")
    for n in needles:
        lines.append(f"  {'HIT ' if n.lower() in low else 'miss'}  {n!r}")
    return "\n".join(lines)


def _snapshot(page: Page, stem: str) -> None:
    # Grab text and DOM back to back, before the slower element inventory: this
    # SPA can advance a step mid-probe, and a .txt describing one page next to a
    # .html of the next one is worse than useless.
    body = page.inner_text("body") or ""
    html = page.content()
    (DATA / f"{stem}.txt").write_text(probe(page, body=body))
    (DATA / f"{stem}.html").write_text(html)
    try:
        page.screenshot(path=str(DATA / f"{stem}.png"), full_page=True)
    except Exception:
        pass
    print(f"  -> wrote {stem}.txt/.html/.png")


def _page_key(page: Page) -> str:
    """Fingerprint of the current page, to notice when the SPA navigates.

    URL alone is useless here: this wizard advances through several steps
    without changing the URL, so key off the body text as well.
    """
    try:
        body = " ".join((page.inner_text("body") or "").split())
    except Exception:
        return ""
    return page.url + "|" + hashlib.sha1(body.encode()).hexdigest()


def follow(page: Page, timeout_s: int = 1_800, poll_s: float = 1.5) -> None:
    """Snapshot every distinct page the *user* navigates to.

    The script never clicks: a human drives the wizard in the open window while
    this records each step. That keeps a UI-mapping run from creating draft
    claims or filing anything the user did not choose to file.
    """
    print(
        "\nFOLLOW MODE — drive the wizard yourself in the browser window.\n"
        "Every page you land on is recorded. Close the window when you're done."
    )
    deadline = time.monotonic() + timeout_s
    seen = {_page_key(page)}
    n = 1
    _snapshot(page, f"probe_wizard_{n:02d}")
    while time.monotonic() < deadline:
        if page.is_closed():
            break
        try:
            page.wait_for_timeout(poll_s * 1000)
            key = _page_key(page)
        except Exception:
            break  # window closed mid-poll
        if not key or key in seen:
            continue
        # Let the SPA settle, then confirm it stopped changing before recording.
        page.wait_for_timeout(1_200)
        key = _page_key(page)
        if key in seen:
            continue
        seen.add(key)
        n += 1
        print(f"\n[{n:02d}] page changed: {page.url}")
        _snapshot(page, f"probe_wizard_{n:02d}")
    print(f"\nRecorded {n} page(s).")


_MEDICAL_CARD = '[data-testid="claims.claimSubmissionTypeCard.card-MEDICAL_CLAIMS-button"]'


def click_medical(page: Page) -> None:
    """Open the Medical claim flow and snapshot the step behind it.

    This is the one click the probe makes on its own. It only navigates into
    the wizard's first step; it submits no form, so it creates no claim. Kept
    separate from --follow because the patient-select step is the page the
    script has to drive and therefore the one whose DOM must be captured
    cleanly.
    """
    _snapshot(page, "probe_select_00_landing")
    print(f"\nClicking {_MEDICAL_CARD} …")
    page.locator(_MEDICAL_CARD).first.click(timeout=15_000)
    page.wait_for_timeout(8_000)
    _snapshot(page, "probe_select_01_after_click")
    # A restored draft or a modal can land us somewhere unexpected; a second
    # look a few seconds later shows whether the page was still settling.
    page.wait_for_timeout(6_000)
    _snapshot(page, "probe_select_02_settled")

    # Claim type -> patient step. Still pure navigation: the draft is only
    # created once a file is uploaded, and we stop well before that.
    print("Choosing 'Doctor or other medical specialist' and Next …")
    page.locator('[data-testid="claims.claimsSubmissionFormTypeSelection.option-0"]').first.click(timeout=15_000)
    page.wait_for_timeout(1_500)
    _snapshot(page, "probe_select_03_type_chosen")
    page.locator('[data-testid="claims.claimsSubmissionFormTypeSelection.next-button"]').first.click(timeout=15_000)
    page.wait_for_timeout(9_000)
    _snapshot(page, "probe_select_04_patient_step")

    # Open the patient dropdown. Reading the option list is the whole point:
    # the script must never guess which household member a claim is for.
    print("Opening the patient dropdown …")
    try:
        page.locator('[data-testid="claims.patientDetails.patient-dropdown"]').first.click(timeout=15_000)
        page.wait_for_timeout(2_500)
        _snapshot(page, "probe_select_05_patient_dropdown_open")
    except Exception as e:
        print(f"  could not open the dropdown: {e}")


def main() -> int:
    follow_mode = "--follow" in sys.argv
    click_mode = "--click-medical" in sys.argv
    username, password = auth.get_credentials()
    with sync_playwright() as pw:
        context = auth.launch_context(pw)
        page = context.new_page()
        try:
            auth.login(page, username, password)
            page.goto(QUESTIONNAIRE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(6_000)  # let the SPA render
            if click_mode:
                click_medical(page)
            elif follow_mode:
                follow(page)
            else:
                report = probe(page)
                (DATA / "probe_wizard.txt").write_text(report)
                (DATA / "probe_wizard.html").write_text(page.content())
                page.screenshot(path=str(DATA / "probe_wizard.png"), full_page=True)
                print(report)
                print(f"\nWrote {DATA / 'probe_wizard.txt'} / .html / .png")
        except Exception as e:
            print(f"[probe] ERROR: {e}")
            return 1
        finally:
            try:
                context.close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
