"""
Combined runner: log in once, fetch claims CSV and benefits in one browser session.

Usage:
    python automation/fetch_all.py

Or set env vars to skip prompts:
    ANTHEM_USERNAME=you@example.com ANTHEM_PASSWORD=secret python automation/fetch_all.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.sync_api import sync_playwright

import auth
import fetch_benefits
import fetch_claims


def main() -> int:
    username, password = auth.get_credentials()
    errors: list[str] = []

    with sync_playwright() as pw:
        context = auth.launch_context(pw)
        page = context.new_page()
        try:
            auth.login(page, username, password)

            # --- Claims CSV ---
            try:
                csv_path = fetch_claims.run(page)
                fetch_claims.post_csv(csv_path)
            except Exception as e:
                print(f"[claims] ERROR: {e}")
                errors.append(f"claims: {e}")

            # --- Benefits ---
            try:
                benefits_data = fetch_benefits.run(page)
                fetch_benefits.save_benefits(benefits_data)
                fetch_benefits.post_benefits(benefits_data)
            except Exception as e:
                print(f"[benefits] ERROR: {e}")
                errors.append(f"benefits: {e}")

        except Exception as e:
            print(f"[auth] ERROR: {e}")
            errors.append(f"auth: {e}")
        finally:
            context.close()

    if errors:
        print(f"\nCompleted with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\nAll done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
