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
