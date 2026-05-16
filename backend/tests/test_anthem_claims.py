from datetime import date
from fastapi.testclient import TestClient
from app.models import AnthemClaim


def _add_claim(db, claim_number="CLM-001", status="Pending"):
    claim = AnthemClaim(
        claim_number=claim_number,
        claim_type="Medical",
        patient_name="James OLeary",
        service_date=date(2025, 11, 4),
        status=status,
        provider_name="Joyful Behavior Therapy",
        billed=240_000, plan_discount=0, allowed=240_000,
        plan_paid=0, additional_savings=0, deductible=0,
        coinsurance=0, copay=0, not_covered=0, your_cost=0,
    )
    db.add(claim)
    db.commit()
    return claim


def test_list_anthem_claims_empty(client: TestClient):
    resp = client.get("/api/anthem-claims")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_anthem_claims(client, db):
    _add_claim(db, "CLM-001", "Pending")
    _add_claim(db, "CLM-002", "Approved")
    resp = client.get("/api/anthem-claims")
    assert len(resp.json()) == 2


def test_filter_by_status(client, db):
    _add_claim(db, "CLM-001", "Pending")
    _add_claim(db, "CLM-002", "Approved")
    resp = client.get("/api/anthem-claims", params={"status": "Approved"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["claim_number"] == "CLM-002"


def test_get_anthem_claim(client, db):
    _add_claim(db)
    resp = client.get("/api/anthem-claims/CLM-001")
    assert resp.status_code == 200
    assert resp.json()["claim_number"] == "CLM-001"


def test_get_anthem_claim_not_found(client: TestClient):
    resp = client.get("/api/anthem-claims/NONEXISTENT")
    assert resp.status_code == 404
