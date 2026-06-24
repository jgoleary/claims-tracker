"""One-time: store credentials in the macOS Keychain.

Anthem (default):
    backend/.venv/bin/python deploy/store_credentials.py
Anthropic API key (PDF auto-fill):
    backend/.venv/bin/python deploy/store_credentials.py --anthropic
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import credentials  # noqa: E402


def _store_anthropic() -> None:
    key = getpass.getpass("Anthropic API key: ").strip()
    if not key:
        print("No key entered; nothing stored.")
        sys.exit(1)
    credentials.store_anthropic_key(key)
    print(f"Stored Anthropic API key in the Keychain (service: {credentials.ANTHROPIC_SERVICE}).")


def _store_anthem() -> None:
    username = input("Anthem email: ").strip()
    password = getpass.getpass("Anthem password: ")
    if not username or not password:
        print("Both fields are required; nothing stored.")
        sys.exit(1)
    credentials.store_credentials(username, password)
    print(f"Stored Anthem credentials in the Keychain (service: {credentials.SERVICE}).")


if __name__ == "__main__":
    if "--anthropic" in sys.argv[1:]:
        _store_anthropic()
    else:
        _store_anthem()
