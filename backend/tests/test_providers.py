from datetime import datetime

from app.models import ProviderAlias


def _add_alias(db, canonical="citrus speech", anthem="citrus speech and language"):
    a = ProviderAlias(canonical_name=canonical, anthem_name=anthem)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_list_aliases_empty(client):
    resp = client.get("/api/providers/aliases")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_aliases(client, db):
    _add_alias(db)
    resp = client.get("/api/providers/aliases")
    assert len(resp.json()) == 1
    assert resp.json()[0]["canonical_name"] == "citrus speech"


def test_delete_alias(client, db):
    alias = _add_alias(db)
    resp = client.delete(f"/api/providers/aliases/{alias.id}")
    assert resp.status_code == 204
    assert client.get("/api/providers/aliases").json() == []


def test_delete_alias_not_found(client):
    resp = client.delete("/api/providers/aliases/9999")
    assert resp.status_code == 404


def test_network_defaults_empty(client):
    resp = client.get("/api/providers/network-defaults")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_network_defaults_returns_most_recent_per_provider(client, db, make_submission):
    # Older submission for "Dr Smith" used out_of_network...
    old = make_submission(provider_name="Dr. Smith", network_treatment="out_of_network")
    old.created_at = datetime(2025, 1, 1)
    # ...a later one switched to in_network_exception (different casing/punctuation).
    new = make_submission(provider_name="dr smith", network_treatment="in_network_exception")
    new.created_at = datetime(2025, 6, 1)
    # A separate provider keeps its own default.
    other = make_submission(provider_name="Joyful Behavior Therapy", network_treatment="out_of_network")
    other.created_at = datetime(2025, 3, 1)
    db.commit()

    body = client.get("/api/providers/network-defaults").json()
    # Both "Dr. Smith" variants normalize to the same key; the most recent wins.
    assert body["dr smith"] == "in_network_exception"
    assert body["joyful behavior therapy"] == "out_of_network"
