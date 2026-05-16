import pytest
import uuid
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Submission, AnthemClaim


@pytest.fixture(scope="function")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture
def make_submission(db: Session):
    def factory(
        member_name: str = "James OLeary",
        provider_name: str = "Joyful Behavior Therapy",
        service_date: date = date(2025, 11, 4),
        amount_billed: int = 240_000,
        expected_reimbursement: int = 180_000,
        network_treatment: str = "out_of_network",
        submitted_date: date = date(2025, 11, 10),
        submission_method: str = "portal",
    ) -> Submission:
        s = Submission(
            id=str(uuid.uuid4()),
            member_name=member_name,
            provider_name=provider_name,
            service_date=service_date,
            amount_billed=amount_billed,
            expected_reimbursement=expected_reimbursement,
            network_treatment=network_treatment,
            submitted_date=submitted_date,
            submission_method=submission_method,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s
    return factory


@pytest.fixture
def make_claim(db: Session):
    def factory(
        claim_number: str = "CLM-001",
        patient_name: str = "James OLeary",
        service_date: date = date(2025, 11, 4),
        status: str = "Pending",
        provider_name: str = "Joyful Behavior Therapy",
        claim_type: str = "Medical",
        billed: int = 240_000,
        plan_discount: int = 0,
        allowed: int = 240_000,
        plan_paid: int = 0,
        additional_savings: int = 0,
        deductible: int = 0,
        coinsurance: int = 0,
        copay: int = 0,
        not_covered: int = 0,
        your_cost: int = 0,
    ) -> AnthemClaim:
        c = AnthemClaim(
            claim_number=claim_number,
            claim_type=claim_type,
            patient_name=patient_name,
            service_date=service_date,
            status=status,
            provider_name=provider_name,
            billed=billed,
            plan_discount=plan_discount,
            allowed=allowed,
            plan_paid=plan_paid,
            additional_savings=additional_savings,
            deductible=deductible,
            coinsurance=coinsurance,
            copay=copay,
            not_covered=not_covered,
            your_cost=your_cost,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return c
    return factory
