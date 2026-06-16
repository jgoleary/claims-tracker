import app.credentials as creds


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
