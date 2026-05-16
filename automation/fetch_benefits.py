"""Scrape the Anthem benefits page and ingest deductible/OOP totals into the backend."""
import json
import re
import sys
from pathlib import Path

# Allow running directly or via fetch_all.py regardless of cwd.
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime

import requests
from playwright.sync_api import Page, sync_playwright

import auth

BENEFITS_URL = "https://membersecure.anthem.com/member/benefits?covtype=med"
BACKEND_URL = "http://localhost:8000"
DATA_DIR = Path("data/exports")

# Tab body IDs in Anthem's Angular SPA.
_IN_NETWORK_TAB_ID = "ant-tab-body-1-0"
_OON_TAB_ID = "ant-tab-body-1-1"

# Selectors to click the Out-of-Network tab (loads OON data on demand).
_OON_TAB_CLICK = [
    '[role="tab"]:has-text("Out-of-Network")',
    '[role="tab"]:has-text("Out of Network")',
    'button:has-text("Out-of-Network")',
    'a:has-text("Out-of-Network")',
]


def scrape_benefits(page: Page) -> dict:
    """Return dict with 'in_network' and 'out_of_network' keys, each a NetworkData dict."""
    print("Navigating to benefits page…")
    page.goto(BENEFITS_URL, wait_until="domcontentloaded", timeout=30_000)
    auth.check_for_site_error(page)

    # Wait for the Angular app to finish rendering benefit cards.
    print("  Waiting for benefit data to render…")
    page.wait_for_selector(".progress-bar-amount", timeout=30_000)

    # Scrape in-network (the default visible tab).
    in_net = _scrape_tab(page, _IN_NETWORK_TAB_ID, "in-network")

    # Click the Out-of-Network tab to trigger its data load, then scrape.
    _click_oon_tab(page)
    out_of_net = _scrape_tab(page, _OON_TAB_ID, "out-of-network")

    return {"in_network": in_net, "out_of_network": out_of_net}


def _click_oon_tab(page: Page) -> None:
    for sel in _OON_TAB_CLICK:
        try:
            el = page.wait_for_selector(sel, timeout=5_000, state="visible")
            if el:
                el.click()
                page.wait_for_timeout(800)
                return
        except Exception:
            continue
    print("  Note: Out-of-Network tab not found; attempting to read current view.")


def _scrape_tab(page: Page, tab_id: str, label: str) -> dict:
    """
    Scrape deductible and OOP max from the given tab body element.

    Anthem's Angular component layout within each tab:
      - 'Your limit is $X' span — one per benefit category (deductible first, OOP second)
      - .progress-bar-amount .label-text spans — two per category (spent, remaining):
          [0]=ded_spent  [1]=ded_remaining  [2]=oop_spent  [3]=oop_remaining
    """
    print(f"  Scraping {label}…")
    tab = page.locator(f"#{tab_id}")

    limit_spans = tab.locator('span:has-text("Your limit is $")').all()
    amount_spans = tab.locator(".progress-bar-amount .label-text").all()

    if len(amount_spans) < 2:
        raise RuntimeError(
            f"Could not find benefit amounts for {label} "
            f"(found {len(amount_spans)} .progress-bar-amount .label-text spans). "
            "Open the benefits page manually and update selectors in fetch_benefits.py."
        )

    def get_text(spans: list, idx: int) -> str:
        if idx < len(spans):
            return (spans[idx].text_content(timeout=2_000) or "").strip()
        return ""

    def get_limit(card_idx: int) -> str:
        text = get_text(limit_spans, card_idx)
        m = re.search(r"\$([\d,]+(?:\.\d{1,2})?)", text)
        if m:
            return f"${m.group(1)}"
        # Fallback: compute from spent + remaining amounts.
        spent_val = _parse_dollar(get_text(amount_spans, card_idx * 2))
        rem_val = _parse_dollar(get_text(amount_spans, card_idx * 2 + 1))
        if spent_val is not None and rem_val is not None:
            return f"${spent_val + rem_val:,.2f}"
        return "unknown"

    # Determine whether there are two distinct benefit cards or just one.
    has_oop = len(amount_spans) >= 3

    return {
        "deductible_spent": get_text(amount_spans, 0),
        "deductible_limit": get_limit(0),
        "oop_spent": get_text(amount_spans, 2) if has_oop else get_text(amount_spans, 0),
        "oop_limit": get_limit(1) if has_oop and len(limit_spans) >= 2 else get_limit(0),
    }


def _parse_dollar(text: str) -> float | None:
    """Parse '$3,162.24' → 3162.24."""
    m = re.search(r"[\d,]+(?:\.\d{1,2})?", text.replace("$", ""))
    if m:
        try:
            return float(m.group().replace(",", ""))
        except ValueError:
            pass
    return None


def save_benefits(data: dict) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    dest = DATA_DIR / f"benefits-{timestamp}.json"
    dest.write_text(json.dumps(data, indent=2))
    print(f"Saved: {dest}")
    return dest


def post_benefits(data: dict) -> bool:
    """POST benefits JSON to the backend. Returns True on success."""
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/ingest/benefits",
            json=data,
            timeout=30,
        )
        resp.raise_for_status()
        print("Benefits ingested.")
        return True
    except Exception as e:
        dest = save_benefits(data)
        print(f"Could not POST to backend ({e}). Upload manually:")
        print(
            f"  curl -X POST {BACKEND_URL}/api/ingest/benefits "
            f"-H 'Content-Type: application/json' -d @{dest.resolve()}"
        )
        return False


def run(page: Page) -> dict:
    """Scrape benefits. Call post_benefits() / save_benefits() separately."""
    return scrape_benefits(page)


def main() -> None:
    username, password = auth.get_credentials()
    with sync_playwright() as pw:
        context = auth.launch_context(pw)
        page = context.new_page()
        try:
            auth.login(page, username, password)
            data = run(page)
            save_benefits(data)
            post_benefits(data)
        finally:
            context.close()


if __name__ == "__main__":
    main()
