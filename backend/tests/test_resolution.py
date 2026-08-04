from datetime import date

from fastapi.testclient import TestClient

from app.resolution import parse_snapshot, snapshot_flags


BASE = "/api/submissions"
_TODAY = date.today().isoformat()

SUBMISSION_BODY = {
    "member_name": "Alex Carter",
    "provider_name": "Sunrise Behavior Therapy",
    "service_date": _TODAY,
    "amount_billed": 57_000,
    "expected_reimbursement": 51_300,
    "network_treatment": "out_of_network",
    "submitted_date": _TODAY,
    "submission_method": "portal",
}

_CSV_HEADER = (
    "Claim #,Type,Patient,Service Date,Status,Provider,"
    "Billed,Plan Discount,Allowed,Plan Paid,Additional Savings,"
    "Deductible,Coinsurance,Copay,Not Covered,Your Cost,Received Date,Processed Date\r\n"
)


def _csv(status: str = "Approved", plan_paid: str = "684.00", your_cost: str = "0.00") -> bytes:
    """One claim that matches SUBMISSION_BODY. Default: paid $684 against an expected
    $513 — an overpayment, the case manual resolution exists for."""
    return (
        _CSV_HEADER
        + f"CLM-001,Medical,Alex Carter (1980-09-20),{_TODAY},{status},Sunrise Behavior Therapy,"
        f"570.00,0.00,570.00,{plan_paid},0.00,0.00,0.00,0.00,0.00,{your_cost},{_TODAY},{_TODAY}\r\n"
    ).encode()


def _ingest(client: TestClient, csv_bytes: bytes):
    return client.post(
        "/api/ingest/claims-csv",
        files={"file": ("claims.csv", csv_bytes, "text/csv")},
    )


def _setup_overpaid(client: TestClient) -> dict:
    """Create a submission, ingest the matching overpaid claim, return the submission."""
    sub = client.post(BASE, json=SUBMISSION_BODY).json()
    _ingest(client, _csv())
    sub = client.get(f"{BASE}/{sub['id']}").json()
    assert [f["flag"] for f in sub["flags"]] == ["OVERPAID"]  # sanity
    return sub


def test_snapshot_round_trip():
    from app.alerts import Alert
    flags = [Alert("OVERPAID", "info"), Alert("DENIED", "red"), Alert("OVERPAID", "info")]
    assert snapshot_flags(flags) == "DENIED,OVERPAID"
    assert parse_snapshot("DENIED,OVERPAID") == {"DENIED", "OVERPAID"}


def test_parse_snapshot_handles_empty():
    assert parse_snapshot(None) == set()
    assert parse_snapshot("") == set()


def test_resolve_snapshots_current_flags(client: TestClient, db):
    from app.models import Submission
    sub = _setup_overpaid(client)
    client.post(f"{BASE}/{sub['id']}/resolve")
    assert db.get(Submission, sub["id"]).resolved_flags == "OVERPAID"


def test_unchanged_ingest_keeps_it_resolved(client: TestClient):
    sub = _setup_overpaid(client)
    client.post(f"{BASE}/{sub['id']}/resolve")

    _ingest(client, _csv())  # same data again

    after = client.get(f"{BASE}/{sub['id']}").json()
    assert after["resolved_at"] is not None
    assert after["flags"] == []


def test_new_flag_reopens(client: TestClient):
    sub = _setup_overpaid(client)
    client.post(f"{BASE}/{sub['id']}/resolve")

    # Anthem reprocesses it as denied — a flag type the snapshot didn't have.
    _ingest(client, _csv(status="Denied"))

    after = client.get(f"{BASE}/{sub['id']}").json()
    assert after["resolved_at"] is None
    assert [f["flag"] for f in after["flags"]] == ["DENIED"]


def test_new_yellow_flag_reopens(client: TestClient):
    sub = _setup_overpaid(client)
    client.post(f"{BASE}/{sub['id']}/resolve")

    # Reprocessed downward: no longer overpaid, now underpaid by $513.
    _ingest(client, _csv(plan_paid="0.00", your_cost="570.00"))

    after = client.get(f"{BASE}/{sub['id']}").json()
    assert after["resolved_at"] is None
    assert any(f["flag"] == "UNDERPAID" for f in after["flags"])


def test_flags_going_away_keeps_it_resolved(client: TestClient):
    """A resolved submission whose flags clear up entirely has nothing new wrong with
    it, so it stays resolved rather than bouncing back into the list."""
    sub = _setup_overpaid(client)
    client.post(f"{BASE}/{sub['id']}/resolve")

    # Paid exactly as expected — no flags at all.
    _ingest(client, _csv(plan_paid="513.00", your_cost="57.00"))

    after = client.get(f"{BASE}/{sub['id']}").json()
    assert after["resolved_at"] is not None


def test_reopened_submission_returns_to_dashboard(client: TestClient):
    sub = _setup_overpaid(client)
    client.post(f"{BASE}/{sub['id']}/resolve")
    hidden = client.get("/api/dashboard").json()
    assert not any(a["submission_id"] == sub["id"] for a in hidden["alerts"])

    _ingest(client, _csv(status="Denied"))

    back = client.get("/api/dashboard").json()
    assert any(a["submission_id"] == sub["id"] and a["flag"] == "DENIED" for a in back["alerts"])


def test_unresolve_clears_the_snapshot(client: TestClient, db):
    from app.models import Submission
    sub = _setup_overpaid(client)
    client.post(f"{BASE}/{sub['id']}/resolve")
    client.delete(f"{BASE}/{sub['id']}/resolve")
    row = db.get(Submission, sub["id"])
    assert row.resolved_at is None and row.resolved_flags is None
