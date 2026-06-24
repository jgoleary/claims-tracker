import app.credentials as creds


def test_anthropic_key_status_configured(client, monkeypatch):
    monkeypatch.setattr(creds, "get_anthropic_key", lambda: "sk-ant-xyz")
    resp = client.get("/api/settings/anthropic-key")
    assert resp.status_code == 200
    assert resp.json() == {"configured": True}


def test_anthropic_key_status_not_configured(client, monkeypatch):
    monkeypatch.setattr(creds, "get_anthropic_key", lambda: None)
    resp = client.get("/api/settings/anthropic-key")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False}
