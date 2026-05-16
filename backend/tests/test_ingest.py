import pytest
from app.ingest import _parse_money, _parse_date, _parse_patient_name, _normalize_status
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.ingest import ingest_claims_csv, ingest_benefits
from app.models import AnthemClaim, BenefitsSnapshot, Match


class TestParseMoney:
    def test_dollar_sign_and_commas(self):
        assert _parse_money("$1,190.00") == 119_000

    def test_plain_number(self):
        assert _parse_money("350.00") == 35_000

    def test_zero(self):
        assert _parse_money("$0.00") == 0

    def test_empty_string(self):
        assert _parse_money("") == 0

    def test_not_available(self):
        assert _parse_money("Not Available") == 0

    def test_quoted_value(self):
        assert _parse_money('"$2,400.00"') == 240_000


class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2025-11-04") == date(2025, 11, 4)

    def test_not_available(self):
        assert _parse_date("Not Available") is None

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_strips_whitespace(self):
        assert _parse_date("  2025-11-04  ") == date(2025, 11, 4)


class TestParsePatientName:
    def test_strips_dob(self):
        assert _parse_patient_name("Nolan O'leary (2019-02-14)") == "Nolan O'leary"

    def test_no_dob(self):
        assert _parse_patient_name("James OLeary") == "James OLeary"

    def test_strips_whitespace(self):
        assert _parse_patient_name("  James OLeary  ") == "James OLeary"


class TestNormalizeStatus:
    def test_pending(self):
        assert _normalize_status("Pending") == "Pending"

    def test_lowercase_approved(self):
        assert _normalize_status("approved") == "Approved"

    def test_uppercase_denied(self):
        assert _normalize_status("DENIED") == "Denied"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown claim status"):
            _normalize_status("Cancelled")


SAMPLE_CSV = """\
Claim #,Type,Patient,Service Date,Status,Provider,Billed,Plan Discount,Allowed,Plan Paid,Additional Savings,Deductible,Coinsurance,Copay,Not Covered,Your Cost,Received Date,Processed Date
CLM-001,Medical,James OLeary (1985-03-12),2025-11-04,Pending,Joyful Behavior Therapy,2400.00,0.00,2400.00,0.00,0.00,0.00,0.00,0.00,0.00,0.00,2025-11-06,Not Available
CLM-002,Medical,Nolan OLeary (2019-02-14),2025-10-01,Approved,California Pacific Medica,"$1,190.00",0.00,"$1,190.00","$952.00",0.00,0.00,"$238.00",0.00,0.00,"$238.00",2025-10-03,2025-10-15
"""

SAMPLE_CSV_BOM = "﻿" + SAMPLE_CSV


class TestIngestClaimsCSV:
    def test_inserts_new_claims(self, db: Session):
        result = ingest_claims_csv(db, SAMPLE_CSV.encode())
        assert result.new == 2
        assert result.updated == 0
        claims = db.scalars(select(AnthemClaim)).all()
        assert len(claims) == 2

    def test_handles_bom(self, db: Session):
        result = ingest_claims_csv(db, SAMPLE_CSV_BOM.encode())
        assert result.new == 2

    def test_upserts_existing_claim(self, db: Session):
        ingest_claims_csv(db, SAMPLE_CSV.encode())
        # Ingest again — same claim numbers, should update not insert
        result = ingest_claims_csv(db, SAMPLE_CSV.encode())
        assert result.new == 0
        assert result.updated == 2
        assert len(db.scalars(select(AnthemClaim)).all()) == 2

    def test_parses_money_correctly(self, db: Session):
        ingest_claims_csv(db, SAMPLE_CSV.encode())
        clm2 = db.get(AnthemClaim, "CLM-002")
        assert clm2.billed == 119_000
        assert clm2.plan_paid == 95_200
        assert clm2.coinsurance == 23_800

    def test_parses_patient_name(self, db: Session):
        ingest_claims_csv(db, SAMPLE_CSV.encode())
        clm1 = db.get(AnthemClaim, "CLM-001")
        assert clm1.patient_name == "James OLeary"

    def test_triggers_matching(self, db: Session, make_submission):
        make_submission(
            member_name="James OLeary",
            provider_name="Joyful Behavior Therapy",
            service_date=date(2025, 11, 4),
        )
        result = ingest_claims_csv(db, SAMPLE_CSV.encode())
        assert result.auto_matched == 1
        match = db.scalars(select(Match)).first()
        assert match is not None
        assert match.match_type == "auto"


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


class TestIngestBenefits:
    def test_creates_two_snapshots(self, db: Session):
        ingest_benefits(db, SAMPLE_BENEFITS)
        snaps = db.scalars(select(BenefitsSnapshot)).all()
        assert len(snaps) == 2

    def test_parses_money_to_cents(self, db: Session):
        ingest_benefits(db, SAMPLE_BENEFITS)
        snaps = {s.network: s for s in db.scalars(select(BenefitsSnapshot)).all()}
        assert snaps["in_network"].deductible_limit == 150_000
        assert snaps["in_network"].deductible_spent == 75_000
        assert snaps["out_of_network"].oop_limit == 600_000

    def test_multiple_ingests_append_snapshots(self, db: Session):
        ingest_benefits(db, SAMPLE_BENEFITS)
        ingest_benefits(db, SAMPLE_BENEFITS)
        assert len(db.scalars(select(BenefitsSnapshot)).all()) == 4
