import uuid
from datetime import date
from fastapi.testclient import TestClient


BASE = "/api/submissions"

# Anchored to today so the submission stays in the current plan year and recent
# enough to avoid the MISSING flag — keeps these tests from rotting over time.
_TODAY = date.today().isoformat()

SUBMISSION_BODY = {
    "member_name": "Alex Carter",
    "provider_name": "Sunrise Behavior Therapy",
    "service_date": _TODAY,
    "amount_billed": 240000,
    "expected_reimbursement": 180000,
    "network_treatment": "out_of_network",
    "submitted_date": _TODAY,
    "submission_method": "portal",
}


def test_create_submission(client: TestClient):
    resp = client.post(BASE, json=SUBMISSION_BODY)
    assert resp.status_code == 201
    data = resp.json()
    assert data["member_name"] == "Alex Carter"
    assert data["flags"] == []
    assert data["anthem_claim_number"] is None


def test_list_submissions(client: TestClient):
    client.post(BASE, json=SUBMISSION_BODY)
    client.post(BASE, json={**SUBMISSION_BODY, "member_name": "Jordan Rivera"})
    resp = client.get(BASE)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_filter_by_member(client: TestClient):
    client.post(BASE, json=SUBMISSION_BODY)
    client.post(BASE, json={**SUBMISSION_BODY, "member_name": "Jordan Rivera"})
    resp = client.get(BASE, params={"member": "Jordan"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["member_name"] == "Jordan Rivera"


def test_get_submission(client: TestClient):
    created = client.post(BASE, json=SUBMISSION_BODY).json()
    resp = client.get(f"{BASE}/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_submission_not_found(client: TestClient):
    resp = client.get(f"{BASE}/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_patch_submission(client: TestClient):
    created = client.post(BASE, json=SUBMISSION_BODY).json()
    resp = client.patch(f"{BASE}/{created['id']}", json={"notes": "Updated note"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated note"


def test_delete_submission(client: TestClient):
    created = client.post(BASE, json=SUBMISSION_BODY).json()
    resp = client.delete(f"{BASE}/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"{BASE}/{created['id']}").status_code == 404


def test_upload_and_download_pdf(client: TestClient):
    created = client.post(BASE, json=SUBMISSION_BODY).json()
    sub_id = created["id"]
    pdf_data = b"%PDF-1.4 fake content"
    resp = client.post(
        f"{BASE}/{sub_id}/pdf",
        files={"file": ("bill.pdf", pdf_data, "application/pdf")},
    )
    assert resp.status_code == 204

    dl = client.get(f"{BASE}/{sub_id}/pdf")
    assert dl.status_code == 200
    assert dl.content == pdf_data


def test_download_pdf_not_found(client: TestClient):
    created = client.post(BASE, json=SUBMISSION_BODY).json()
    resp = client.get(f"{BASE}/{created['id']}/pdf")
    assert resp.status_code == 404


def test_create_submission_without_submitted_date(client):
    resp = client.post("/api/submissions", json={
        "member_name": "Alex Carter",
        "provider_name": "Sunrise Behavior Therapy",
        "service_date": "2026-05-06",
        "amount_billed": 57000,
        "expected_reimbursement": 25900,
        "network_treatment": "out_of_network",
        "submission_method": "portal",
    })
    assert resp.status_code == 201
    assert resp.json()["submitted_date"] is None


def _make_old_and_new(client: TestClient):
    """Create an old submission overdue enough to flag MISSING, plus a follow-up."""
    from datetime import timedelta
    from app import config
    old_date = (date.today() - timedelta(days=config.MISSING_DAYS + 1)).isoformat()
    old = client.post(BASE, json={
        **SUBMISSION_BODY, "service_date": old_date, "submitted_date": old_date,
    }).json()
    new = client.post(BASE, json={**SUBMISSION_BODY, "member_name": "Alex Carter"}).json()
    return old, new


def test_supersede_sets_pointer_and_clears_flags(client: TestClient):
    old, new = _make_old_and_new(client)
    assert any(f["flag"] == "MISSING" for f in old["flags"])  # sanity: it was interesting

    resp = client.post(f"{BASE}/{old['id']}/supersede", json={"superseded_by_id": new["id"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["flags"] == []
    assert data["superseded_by"]["id"] == new["id"]
    assert data["superseded_by"]["provider_name"] == new["provider_name"]

    # Reverse link shows on the successor.
    successor = client.get(f"{BASE}/{new['id']}").json()
    assert [s["id"] for s in successor["supersedes"]] == [old["id"]]


def test_superseded_submission_absent_from_dashboard(client: TestClient):
    old, new = _make_old_and_new(client)
    before = client.get("/api/dashboard").json()
    assert any(a["submission_id"] == old["id"] for a in before["alerts"])

    client.post(f"{BASE}/{old['id']}/supersede", json={"superseded_by_id": new["id"]})
    after = client.get("/api/dashboard").json()
    assert not any(a["submission_id"] == old["id"] for a in after["alerts"])


def test_unsupersede_restores(client: TestClient):
    old, new = _make_old_and_new(client)
    client.post(f"{BASE}/{old['id']}/supersede", json={"superseded_by_id": new["id"]})

    resp = client.delete(f"{BASE}/{old['id']}/supersede")
    assert resp.status_code == 200
    data = resp.json()
    assert data["superseded_by"] is None
    assert any(f["flag"] == "MISSING" for f in data["flags"])


def test_supersede_self_rejected(client: TestClient):
    created = client.post(BASE, json=SUBMISSION_BODY).json()
    resp = client.post(f"{BASE}/{created['id']}/supersede", json={"superseded_by_id": created["id"]})
    assert resp.status_code == 400


def test_supersede_unknown_successor_404(client: TestClient):
    created = client.post(BASE, json=SUBMISSION_BODY).json()
    resp = client.post(f"{BASE}/{created['id']}/supersede", json={"superseded_by_id": str(uuid.uuid4())})
    assert resp.status_code == 404


def test_deleting_successor_clears_pointer(client: TestClient):
    old, new = _make_old_and_new(client)
    client.post(f"{BASE}/{old['id']}/supersede", json={"superseded_by_id": new["id"]})

    assert client.delete(f"{BASE}/{new['id']}").status_code == 204
    old_after = client.get(f"{BASE}/{old['id']}").json()
    assert old_after["superseded_by"] is None
    assert any(f["flag"] == "MISSING" for f in old_after["flags"])  # interesting again


def _make_flagged(client: TestClient):
    """Create a submission overdue enough to raise the MISSING flag."""
    from datetime import timedelta
    from app import config
    old_date = (date.today() - timedelta(days=config.MISSING_DAYS + 1)).isoformat()
    return client.post(BASE, json={
        **SUBMISSION_BODY, "service_date": old_date, "submitted_date": old_date,
    }).json()


def test_resolve_sets_timestamp_and_clears_flags(client: TestClient):
    sub = _make_flagged(client)
    assert any(f["flag"] == "MISSING" for f in sub["flags"])  # sanity: it was interesting

    resp = client.post(f"{BASE}/{sub['id']}/resolve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["resolved_at"] is not None
    assert data["flags"] == []


def test_resolved_submission_absent_from_dashboard(client: TestClient):
    sub = _make_flagged(client)
    before = client.get("/api/dashboard").json()
    assert any(a["submission_id"] == sub["id"] for a in before["alerts"])

    client.post(f"{BASE}/{sub['id']}/resolve")
    after = client.get("/api/dashboard").json()
    assert not any(a["submission_id"] == sub["id"] for a in after["alerts"])
    assert after["counts"]["missing"] == 0


def test_unresolve_restores_flags(client: TestClient):
    sub = _make_flagged(client)
    client.post(f"{BASE}/{sub['id']}/resolve")

    resp = client.delete(f"{BASE}/{sub['id']}/resolve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["resolved_at"] is None
    assert any(f["flag"] == "MISSING" for f in data["flags"])


def test_resolve_unknown_submission_404(client: TestClient):
    missing_id = str(uuid.uuid4())
    assert client.post(f"{BASE}/{missing_id}/resolve").status_code == 404
    assert client.delete(f"{BASE}/{missing_id}/resolve").status_code == 404


def test_extract_returns_not_configured_without_key(client, monkeypatch):
    # The key resolves Keychain -> env var, so neutralize both. Without the
    # Keychain stub this test fails on any machine that has a real key stored.
    monkeypatch.setattr("app.extraction.credentials.get_anthropic_key", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/submissions/extract",
        files={"file": ("claim.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
