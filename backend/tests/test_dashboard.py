from datetime import date, timedelta
from app.models import AnthemClaim, BenefitsSnapshot, Match, Submission
import uuid


def _add_submission(db, submitted_date=None, provider="Joyful Behavior Therapy"):
    s = Submission(
        id=str(uuid.uuid4()),
        member_name="James OLeary",
        provider_name=provider,
        service_date=date(2026, 4, 28),
        amount_billed=240_000,
        expected_reimbursement=180_000,
        network_treatment="out_of_network",
        submitted_date=submitted_date or date.today(),
        submission_method="portal",
    )
    db.add(s)
    db.commit()
    return s


def test_dashboard_empty(client):
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"] == {"missing": 0, "stale_pending": 0, "denied": 0, "underpaid": 0, "vanished": 0}
    assert data["alerts"] == []


def test_dashboard_missing_flag(client, db):
    _add_submission(db, submitted_date=date.today() - timedelta(days=35))
    resp = client.get("/api/dashboard")
    data = resp.json()
    assert data["counts"]["missing"] == 1
    assert any(a["flag"] == "MISSING" for a in data["alerts"])


def test_dashboard_denied_flag(client, db):
    sub = _add_submission(db)
    claim = AnthemClaim(
        claim_number="CLM-001", claim_type="Medical", patient_name="James OLeary",
        service_date=date(2026, 4, 28), status="Denied",
        provider_name="Joyful Behavior Therapy",
        billed=240_000, plan_discount=0, allowed=0, plan_paid=0,
        additional_savings=0, deductible=0, coinsurance=0, copay=0,
        not_covered=240_000, your_cost=240_000,
    )
    db.add(claim)
    db.add(Match(submission_id=sub.id, anthem_claim_number="CLM-001", match_type="auto"))
    db.commit()
    resp = client.get("/api/dashboard")
    data = resp.json()
    assert data["counts"]["denied"] == 1
    assert any(a["flag"] == "DENIED" and a["severity"] == "red" for a in data["alerts"])
