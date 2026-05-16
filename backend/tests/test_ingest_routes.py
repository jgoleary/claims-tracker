from sqlalchemy import select
from app.models import AnthemClaim, BenefitsSnapshot

SAMPLE_CSV = (
    "Claim #,Type,Patient,Service Date,Status,Provider,"
    "Billed,Plan Discount,Allowed,Plan Paid,Additional Savings,"
    "Deductible,Coinsurance,Copay,Not Covered,Your Cost,Received Date,Processed Date\r\n"
    "CLM-001,Medical,James OLeary (1985-03-12),2025-11-04,Pending,Joyful Behavior Therapy,"
    "2400.00,0.00,2400.00,0.00,0.00,0.00,0.00,0.00,0.00,0.00,2025-11-06,Not Available\r\n"
)

SAMPLE_BENEFITS = {
    "in_network": {
        "deductible_limit": "$1,500.00",
        "deductible_spent": "$750.00",
        "oop_limit": "$3,000.00",
        "oop_spent": "$1,200.00",
    },
    "out_of_network": {
        "deductible_limit": "$3,000.00",
        "deductible_spent": "$500.00",
        "oop_limit": "$6,000.00",
        "oop_spent": "$800.00",
    },
}


def test_ingest_csv(client, db):
    resp = client.post(
        "/api/ingest/claims-csv",
        files={"file": ("claims.csv", SAMPLE_CSV.encode(), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["new"] == 1
    assert data["updated"] == 0
    assert len(db.scalars(select(AnthemClaim)).all()) == 1


def test_ingest_csv_upsert(client, db):
    client.post(
        "/api/ingest/claims-csv",
        files={"file": ("claims.csv", SAMPLE_CSV.encode(), "text/csv")},
    )
    resp = client.post(
        "/api/ingest/claims-csv",
        files={"file": ("claims.csv", SAMPLE_CSV.encode(), "text/csv")},
    )
    assert resp.json()["updated"] == 1
    assert len(db.scalars(select(AnthemClaim)).all()) == 1


def test_ingest_csv_wrong_extension(client):
    resp = client.post(
        "/api/ingest/claims-csv",
        files={"file": ("claims.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 422


def test_ingest_benefits(client, db):
    resp = client.post("/api/ingest/benefits", json=SAMPLE_BENEFITS)
    assert resp.status_code == 204
    snaps = db.scalars(select(BenefitsSnapshot)).all()
    assert len(snaps) == 2


def test_ingest_benefits_appends(client, db):
    client.post("/api/ingest/benefits", json=SAMPLE_BENEFITS)
    client.post("/api/ingest/benefits", json=SAMPLE_BENEFITS)
    assert len(db.scalars(select(BenefitsSnapshot)).all()) == 4
