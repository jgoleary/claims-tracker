"""
Escalate a stuck claim to Included Health.

Drives the IH claims-support form: select "Out-of-network charges", pick the
member, fill the service date / provider / message, then STOP before Submit so
the user reviews and submits in the browser window.

Inputs come from env vars (set by backend/app/automation.py:run_escalation):
    IH_SUBMISSION_ID, IH_MEMBER, IH_PROVIDER, IH_SERVICE_DATE (YYYY-MM-DD), IH_MESSAGE

Usage (manual):
    IH_MEMBER="Nolan O'Leary" IH_PROVIDER="Dr X" IH_SERVICE_DATE=2025-11-04 \
        IH_MESSAGE="…" python automation/ih_escalate.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.sync_api import Page, sync_playwright

import ih_auth

# Leave the window open this long for the user to review and submit. Kept below
# the backend subprocess timeout (600s) so we exit cleanly rather than be killed.
_REVIEW_TIMEOUT_MS = 540_000


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
        f"Update ih_escalate.py if Included Health changed their form."
    )


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
        f"Could not fill {name}.\n"
        f"Selectors tried: {selectors}\n"
        f"Update ih_escalate.py if Included Health changed their form."
    )


def _click_member(page: Page, member: str) -> None:
    """Click the household member card. IH may show the full name while the
    submission holds only a first name (or vice versa) — try both."""
    first = member.split()[0] if member.split() else member
    for name in [member, first]:
        if not name:
            continue
        try:
            page.get_by_text(name, exact=False).first.click(timeout=8_000)
            return
        except Exception:
            continue
    raise RuntimeError(
        f"Could not find member '{member}' on the 'Who is this for?' screen."
    )


def fill_form(page: Page, member: str, provider: str, service_date: str, message: str) -> None:
    # 1. "What can we help you with?" → Out-of-network charges
    _click_text(page, ["Out-of-network charges"], "the 'Out-of-network charges' option")

    # 2. "Who is this for?" → the member
    _click_member(page, member)

    # 3. "Tell us about your experience" → date, provider, message
    _fill_first(page, ['input[type="date"]'], service_date, "service date")
    _fill_first(page, [
        'input[placeholder*="Dr. Dan Jones" i]',
        'input[placeholder*="provider" i]',
    ], provider, "provider name")
    _fill_first(page, [
        'textarea[placeholder*="diagnostic" i]',
        'textarea',
    ], message, "the contesting-reason message")

    # Stop before Submit — the user reviews and submits in the browser.
    print(
        "Form filled — review and click Submit in the browser window. "
        "Close the window when you're done."
    )
    try:
        page.wait_for_event("close", timeout=_REVIEW_TIMEOUT_MS)
    except Exception:
        pass  # timed out waiting for the user — leave the form prepared


def main() -> int:
    member = os.environ.get("IH_MEMBER", "")
    provider = os.environ.get("IH_PROVIDER", "")
    service_date = os.environ.get("IH_SERVICE_DATE", "")
    message = os.environ.get("IH_MESSAGE", "")

    errors: list[str] = []
    with sync_playwright() as pw:
        context = ih_auth.launch_context(pw)
        page = context.new_page()
        try:
            ih_auth.login(page)
            try:
                fill_form(page, member, provider, service_date, message)
            except Exception as e:
                print(f"[form] ERROR: {e}")
                errors.append(f"form: {e}")
        except Exception as e:
            print(f"[auth] ERROR: {e}")
            errors.append(f"auth: {e}")
        finally:
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
