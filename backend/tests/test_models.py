import uuid
from datetime import date, datetime
from sqlalchemy.orm import Session

from app.models import (
    Submission, AnthemClaim, Match, ProviderAlias, BenefitsSnapshot
)


def test_create_submission(db: Session):
    s = Submission(
        id=str(uuid.uuid4()),
        member_name="James OLeary",
        provider_name="Joyful Behavior Therapy",
        service_date=date(2025, 11, 4),
        amount_billed=240_000,
        expected_reimbursement=180_000,
        network_treatment="out_of_network",
        submitted_date=date(2025, 11, 10),
        submission_method="portal",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    assert db.get(Submission, s.id) is not None


def test_create_anthem_claim(db: Session):
    c = AnthemClaim(
        claim_number="CLM-001",
        claim_type="Medical",
        patient_name="James OLeary",
        service_date=date(2025, 11, 4),
        status="Pending",
        provider_name="Joyful Behavior Therapy",
        billed=240_000,
        plan_discount=0,
        allowed=240_000,
        plan_paid=0,
        additional_savings=0,
        deductible=0,
        coinsurance=0,
        copay=0,
        not_covered=0,
        your_cost=0,
    )
    db.add(c)
    db.commit()
    assert db.get(AnthemClaim, "CLM-001") is not None


def test_create_match(db: Session, make_submission, make_claim):
    s = make_submission()
    c = make_claim()
    m = Match(
        submission_id=s.id,
        anthem_claim_number=c.claim_number,
        match_type="auto",
    )
    db.add(m)
    db.commit()
    assert db.get(Match, s.id) is not None


def test_create_provider_alias(db: Session):
    a = ProviderAlias(canonical_name="joyful behavior therapy", anthem_name="joyful behavior therapy l")
    db.add(a)
    db.commit()
    assert a.id is not None


def test_create_benefits_snapshot(db: Session):
    snap = BenefitsSnapshot(
        snapshot_date=datetime(2025, 11, 15),
        network="out_of_network",
        deductible_limit=300_000,
        deductible_spent=150_000,
        oop_limit=600_000,
        oop_spent=200_000,
    )
    db.add(snap)
    db.commit()
    assert snap.id is not None
