"""Credential resolution for the Anthem automation scripts.

Order is env vars → macOS Keychain → interactive prompt. The Keychain step
exists so a manual run (`python automation/submit_claim.py`) works without
exporting anything; the backend-spawned path always sets the env vars and so
never reaches it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "automation"))
import auth  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("ANTHEM_USERNAME", raising=False)
    monkeypatch.delenv("ANTHEM_PASSWORD", raising=False)


def _no_prompt(monkeypatch):
    """Make any prompt a hard failure — tests must never block on stdin."""
    def boom(*a, **k):
        raise AssertionError("prompted for credentials unexpectedly")
    monkeypatch.setattr("builtins.input", boom)
    monkeypatch.setattr(auth.getpass, "getpass", boom)


def test_env_vars_win_over_keychain(monkeypatch):
    monkeypatch.setenv("ANTHEM_USERNAME", "env@example.com")
    monkeypatch.setenv("ANTHEM_PASSWORD", "env-pw")
    monkeypatch.setattr(auth, "keychain_credentials",
                        lambda: ("keychain@example.com", "keychain-pw"))
    _no_prompt(monkeypatch)
    assert auth.get_credentials() == ("env@example.com", "env-pw")


def test_falls_back_to_keychain(monkeypatch):
    monkeypatch.setattr(auth, "keychain_credentials",
                        lambda: ("keychain@example.com", "keychain-pw"))
    _no_prompt(monkeypatch)
    assert auth.get_credentials() == ("keychain@example.com", "keychain-pw")


def test_partial_env_falls_back_to_keychain(monkeypatch):
    # Half-set env is not usable; the Keychain pair is preferred over prompting.
    monkeypatch.setenv("ANTHEM_USERNAME", "env@example.com")
    monkeypatch.setattr(auth, "keychain_credentials",
                        lambda: ("keychain@example.com", "keychain-pw"))
    _no_prompt(monkeypatch)
    assert auth.get_credentials() == ("keychain@example.com", "keychain-pw")


def test_prompts_when_nothing_stored(monkeypatch):
    monkeypatch.setattr(auth, "keychain_credentials", lambda: None)
    monkeypatch.setattr("builtins.input", lambda *a: " typed@example.com ")
    monkeypatch.setattr(auth.getpass, "getpass", lambda *a: "typed-pw")
    assert auth.get_credentials() == ("typed@example.com", "typed-pw")


def test_partial_env_prompts_only_for_the_missing_half(monkeypatch):
    monkeypatch.setenv("ANTHEM_USERNAME", "env@example.com")
    monkeypatch.setattr(auth, "keychain_credentials", lambda: None)
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(
        AssertionError("should not prompt for the username")))
    monkeypatch.setattr(auth.getpass, "getpass", lambda *a: "typed-pw")
    assert auth.get_credentials() == ("env@example.com", "typed-pw")


def test_keychain_failure_is_swallowed(monkeypatch):
    """A locked or unavailable Keychain must not crash the script."""
    import app.credentials as _creds

    monkeypatch.setattr(_creds, "get_credentials",
                        lambda: (_ for _ in ()).throw(RuntimeError("locked")))
    assert auth.keychain_credentials() is None


def test_keychain_credentials_reads_the_backend_keyring(monkeypatch):
    import app.credentials as _creds

    monkeypatch.setattr(_creds, "get_credentials", lambda: ("a@b.com", "pw"))
    assert auth.keychain_credentials() == ("a@b.com", "pw")
