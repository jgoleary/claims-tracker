from datetime import date, datetime, timezone
from app.models import AnthemClaim, BenefitsSnapshot, Match, Submission
import uuid


def _add_snapshot(db, network, deductible_spent, oop_spent, deductible_limit=300_000, oop_limit=600_000):
    db.add(BenefitsSnapshot(
        snapshot_date=datetime.now(timezone.utc),
        network=network,
        deductible_limit=deductible_limit,
        deductible_spent=deductible_spent,
        oop_limit=oop_limit,
        oop_spent=oop_spent,
    ))
    db.commit()


def test_totals_no_data(client):
    resp = client.get("/api/totals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["in_network"]["benefits"] is None
    assert data["in_network"]["csv_rollup"]["total_sum"] == 0
    assert data["out_of_network"]["csv_rollup"]["total_sum"] == 0


def test_totals_with_snapshots(client, db):
    _add_snapshot(db, "in_network", deductible_spent=75_000, oop_spent=120_000)
    _add_snapshot(db, "out_of_network", deductible_spent=50_000, oop_spent=80_000)
    resp = client.get("/api/totals")
    data = resp.json()
    assert data["in_network"]["benefits"]["deductible_spent"] == 75_000
    assert data["out_of_network"]["benefits"]["oop_spent"] == 80_000


def test_totals_csv_rollup_unmatched_defaults_in_network(client, db):
    # Unmatched claim defaults to in_network bucket
    claim = AnthemClaim(
        claim_number="CLM-001", claim_type="Medical",
        patient_name="James OLeary", service_date=date.today(),
        status="Approved", provider_name="Dr. Smith",
        billed=100_000, plan_discount=0, allowed=100_000,
        plan_paid=80_000, additional_savings=0,
        deductible=10_000, coinsurance=10_000,
        copay=0, not_covered=0, your_cost=20_000,
    )
    db.add(claim)
    db.commit()
    resp = client.get("/api/totals")
    data = resp.json()
    assert data["in_network"]["csv_rollup"]["deductible_sum"] == 10_000
    assert data["in_network"]["csv_rollup"]["total_sum"] == 20_000
    # In-network spending also counts toward the OON accumulator (see _get_csv_rollup).
    assert data["out_of_network"]["csv_rollup"]["total_sum"] == 20_000
