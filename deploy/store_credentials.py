"""One-time: store Anthem credentials in the macOS Keychain.

Run with the backend venv:
    backend/.venv/bin/python deploy/store_credentials.py
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import credentials  # noqa: E402

username = input("Anthem email: ").strip()
password = getpass.getpass("Anthem password: ")
if not username or not password:
    print("Both fields are required; nothing stored.")
    sys.exit(1)
credentials.store_credentials(username, password)
print(f"Stored Anthem credentials in the Keychain (service: {credentials.SERVICE}).")
