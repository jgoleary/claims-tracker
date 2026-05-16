from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnthemClaim
from app.schemas import AnthemClaimResponse

router = APIRouter()


def _to_response(claim: AnthemClaim) -> AnthemClaimResponse:
    return AnthemClaimResponse(
        claim_number=claim.claim_number,
        claim_type=claim.claim_type,
        patient_name=claim.patient_name,
        service_date=claim.service_date,
        received_date=claim.received_date,
        processed_date=claim.processed_date,
        status=claim.status,
        provider_name=claim.provider_name,
        billed=claim.billed,
        plan_discount=claim.plan_discount,
        allowed=claim.allowed,
        plan_paid=claim.plan_paid,
        additional_savings=claim.additional_savings,
        deductible=claim.deductible,
        coinsurance=claim.coinsurance,
        copay=claim.copay,
        not_covered=claim.not_covered,
        your_cost=claim.your_cost,
        first_seen_at=claim.first_seen_at,
        last_seen_at=claim.last_seen_at,
        is_matched=claim.match is not None,
    )


@router.get("/anthem-claims", response_model=list[AnthemClaimResponse])
def list_anthem_claims(
    matched: Optional[str] = None,
    status: Optional[str] = None,
    patient: Optional[str] = None,
    db: Session = Depends(get_db),
):
    claims = db.scalars(select(AnthemClaim)).all()
    results = [_to_response(c) for c in claims]

    if matched == "true":
        results = [r for r in results if r.is_matched]
    elif matched == "false":
        results = [r for r in results if not r.is_matched]
    if status:
        results = [r for r in results if r.status == status]
    if patient:
        results = [r for r in results if patient.lower() in r.patient_name.lower()]

    return results


@router.get("/anthem-claims/{claim_number}", response_model=AnthemClaimResponse)
def get_anthem_claim(claim_number: str, db: Session = Depends(get_db)):
    claim = db.get(AnthemClaim, claim_number)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return _to_response(claim)
