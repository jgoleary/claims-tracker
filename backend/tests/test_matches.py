from datetime import date
from fastapi.testclient import TestClient
from app.models import AnthemClaim


SUBMISSION_BODY = {
    "member_name": "James OLeary",
    "provider_name": "Joyful Behavior Therapy",
    "service_date": "2026-04-28",
    "amount_billed": 240000,
    "expected_reimbursement": 180000,
    "network_treatment": "out_of_network",
    "submitted_date": "2026-05-01",
    "submission_method": "portal",
}


def _create_submission(client):
    return client.post("/api/submissions", json=SUBMISSION_BODY).json()


def _add_claim(db, claim_number="CLM-001"):
    c = AnthemClaim(
        claim_number=claim_number, claim_type="Medical",
        patient_name="James OLeary", service_date=date(2026, 4, 28),
        status="Pending", provider_name="Joyful Behavior Therapy",
        billed=240_000, plan_discount=0, allowed=240_000,
        plan_paid=0, additional_savings=0, deductible=0,
        coinsurance=0, copay=0, not_covered=0, your_cost=0,
    )
    db.add(c)
    db.commit()
    return c


def test_create_manual_match(client, db):
    sub = _create_submission(client)
    _add_claim(db)
    resp = client.post("/api/matches", json={
        "submission_id": sub["id"],
        "anthem_claim_number": "CLM-001",
        "match_type": "manual",
    })
    assert resp.status_code == 201


def test_duplicate_submission_match_returns_409(client, db):
    sub = _create_submission(client)
    _add_claim(db)
    client.post("/api/matches", json={
        "submission_id": sub["id"],
        "anthem_claim_number": "CLM-001",
        "match_type": "manual",
    })
    resp = client.post("/api/matches", json={
        "submission_id": sub["id"],
        "anthem_claim_number": "CLM-001",
        "match_type": "manual",
    })
    assert resp.status_code == 409


def test_delete_match(client, db):
    sub = _create_submission(client)
    _add_claim(db)
    client.post("/api/matches", json={
        "submission_id": sub["id"],
        "anthem_claim_number": "CLM-001",
        "match_type": "manual",
    })
    resp = client.delete(f"/api/matches/{sub['id']}")
    assert resp.status_code == 204


def test_delete_match_not_found(client):
    import uuid
    resp = client.delete(f"/api/matches/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_suggestions_empty(client):
    resp = client.get("/api/matches/suggestions")
    assert resp.status_code == 200
    assert resp.json() == []
