"""Scrape the Anthem benefits page and ingest deductible/OOP totals into the backend."""
import json
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

# Anthem rebuilt this page as a react-native-web micro-app (release 2026-09-25):
# ?covtype=med now redirects to /member/benefits/landing, and the Angular tab
# bodies (#ant-tab-body-1-*) and .progress-bar-amount spans are gone. The "Plan
# details & progress" section lists both networks side by side, so no tab click
# is needed. Select by data-testid only — the css-*/r-* classes change per build.
_SECTION = '[data-testid="benefits.planDetailsSection.section-{}"]'
_DEDUCTIBLE = "Deductible"
_OOP = "OutOfPocketMaximum"
_CARD = '[data-testid="benefits.networkProgressCard.card"]'
_CARD_FIELD = '[data-testid="benefits.networkProgressCard.{}"]'

# Card network label ("Participating Network: $3,400.00") → output key.
_NETWORKS = {
    "in_network": "Participating Network",
    "out_of_network": "Out of Network",
}


def scrape_benefits(page: Page) -> dict:
    """Return dict with 'in_network' and 'out_of_network' keys, each a NetworkData dict."""
    print("Navigating to benefits page…")
    page.goto(BENEFITS_URL, wait_until="domcontentloaded", timeout=30_000)
    auth.check_for_site_error(page)

    print("  Waiting for benefit data to render…")
    try:
        # The accordions start collapsed (height 0) but their cards are in the
        # DOM, so wait for attachment, not visibility.
        page.wait_for_selector(
            f"{_SECTION.format(_DEDUCTIBLE)} {_CARD}", state="attached", timeout=30_000
        )
    except Exception:
        auth.check_session_alive(page)
        raise RuntimeError(
            "No deductible cards on the benefits page "
            f"({page.url}). Update _SECTION / _CARD in fetch_benefits.py to match "
            "Anthem's current UI."
        )

    deductible = _read_section(page, _DEDUCTIBLE)
    oop = _read_section(page, _OOP)
    return {
        key: {
            "deductible_spent": deductible[key]["spent"],
            "deductible_limit": deductible[key]["limit"],
            "oop_spent": oop[key]["spent"],
            "oop_limit": oop[key]["limit"],
        }
        for key in _NETWORKS
    }


def _read_section(page: Page, section: str) -> dict[str, dict[str, str]]:
    """{network key: {"limit", "spent"}} from one section's progress cards.

    text_content(), not inner_text(): the section is a collapsed accordion, and
    inner_text() reads nothing from a hidden node.
    """
    cards = page.locator(f"{_SECTION.format(section)} {_CARD}")
    found: dict[str, dict[str, str]] = {}
    for i in range(cards.count()):
        card = cards.nth(i)
        network = _field(card, "networkDisplay")
        for key, label in _NETWORKS.items():
            # First card per network wins — the family row, which is what the
            # plan's accumulators track.
            if network.startswith(label) and key not in found:
                found[key] = {
                    "limit": _field(card, "totalValue"),
                    "spent": _field(card, "spentValue"),
                }

    missing = [_NETWORKS[k] for k in _NETWORKS if k not in found]
    if missing:
        raise RuntimeError(
            f"Benefits section {section!r} has no card for {', '.join(missing)} "
            f"({cards.count()} cards found). Update _SECTION / _CARD / _NETWORKS in "
            "fetch_benefits.py to match Anthem's current UI."
        )
    return found


def _field(card, name: str) -> str:
    return (card.locator(_CARD_FIELD.format(name)).first.text_content(timeout=2_000) or "").strip()


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
