from keyring.errors import KeyringLocked

import app.credentials as creds


class _LockedKeyring:
    """Simulates a denied/locked Keychain (e.g. the user clicked Deny)."""

    def get_password(self, service, key):
        raise KeyringLocked("Can't get password from keychain: (-128, 'Keychain Access Denied')")

    def set_password(self, service, key, value):
        raise KeyringLocked("denied")


class _FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, key, value):
        self.store[(service, key)] = value

    def get_password(self, service, key):
        return self.store.get((service, key))


def test_store_and_get_roundtrip(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _FakeKeyring())
    creds.store_credentials("me@example.com", "s3cret")
    assert creds.get_credentials() == ("me@example.com", "s3cret")


def test_get_returns_none_when_unset(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _FakeKeyring())
    assert creds.get_credentials() is None


def test_get_returns_none_when_password_missing(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(creds, "keyring", fake)
    fake.set_password(creds.SERVICE, "username", "me@example.com")
    assert creds.get_credentials() is None


def test_anthropic_key_roundtrip(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _FakeKeyring())
    creds.store_anthropic_key("sk-ant-abc123")
    assert creds.get_anthropic_key() == "sk-ant-abc123"


def test_anthropic_key_none_when_unset(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _FakeKeyring())
    assert creds.get_anthropic_key() is None


def test_anthropic_key_none_when_empty(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(creds, "keyring", fake)
    fake.set_password(creds.ANTHROPIC_SERVICE, "api_key", "")
    assert creds.get_anthropic_key() is None


def test_anthropic_key_none_when_keychain_locked(monkeypatch):
    # A denied/locked Keychain must degrade to "not configured", not raise.
    monkeypatch.setattr(creds, "keyring", _LockedKeyring())
    assert creds.get_anthropic_key() is None


def test_get_credentials_none_when_keychain_locked(monkeypatch):
    monkeypatch.setattr(creds, "keyring", _LockedKeyring())
    assert creds.get_credentials() is None
