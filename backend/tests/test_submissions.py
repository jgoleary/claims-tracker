import uuid
from datetime import date
from fastapi.testclient import TestClient


BASE = "/api/submissions"

# Anchored to today so the submission stays in the current plan year and recent
# enough to avoid the MISSING flag — keeps these tests from rotting over time.
_TODAY = date.today().isoformat()

SUBMISSION_BODY = {
    "member_name": "James OLeary",
    "provider_name": "Joyful Behavior Therapy",
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
    assert data["member_name"] == "James OLeary"
    assert data["flags"] == []
    assert data["anthem_claim_number"] is None


def test_list_submissions(client: TestClient):
    client.post(BASE, json=SUBMISSION_BODY)
    client.post(BASE, json={**SUBMISSION_BODY, "member_name": "Nolan OLeary"})
    resp = client.get(BASE)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_filter_by_member(client: TestClient):
    client.post(BASE, json=SUBMISSION_BODY)
    client.post(BASE, json={**SUBMISSION_BODY, "member_name": "Nolan OLeary"})
    resp = client.get(BASE, params={"member": "Nolan"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["member_name"] == "Nolan OLeary"


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
        "member_name": "James OLeary",
        "provider_name": "Joyful Behavior Therapy",
        "service_date": "2026-05-06",
        "amount_billed": 57000,
        "expected_reimbursement": 25900,
        "network_treatment": "out_of_network",
        "submission_method": "portal",
    })
    assert resp.status_code == 201
    assert resp.json()["submitted_date"] is None


def test_extract_returns_not_configured_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/submissions/extract",
        files={"file": ("claim.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
