import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.alerts import compute_flags
from app.config import plan_year_dates
from app.database import get_db
from app.matching import run_matching
from app.models import Match, Submission
from app.schemas import AlertOut, SubmissionCreate, SubmissionResponse, SubmissionUpdate
from app.storage import get_storage

router = APIRouter()


def _to_response(submission: Submission) -> SubmissionResponse:
    match = submission.match
    flags = compute_flags(submission, match)
    return SubmissionResponse(
        id=submission.id,
        member_name=submission.member_name,
        provider_name=submission.provider_name,
        service_date=submission.service_date,
        amount_billed=submission.amount_billed,
        expected_reimbursement=submission.expected_reimbursement,
        network_treatment=submission.network_treatment,
        submitted_date=submission.submitted_date,
        submission_method=submission.submission_method,
        pdf_path=submission.pdf_path,
        notes=submission.notes,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
        anthem_claim_number=match.anthem_claim_number if match else None,
        anthem_claim_status=match.anthem_claim.status if match and match.anthem_claim else None,
        anthem_plan_paid=match.anthem_claim.plan_paid if match and match.anthem_claim else None,
        flags=[AlertOut(flag=a.flag, severity=a.severity, details=a.details) for a in flags],
    )


def _load_options():
    return selectinload(Submission.match).selectinload(Match.anthem_claim)


@router.get("/submissions", response_model=list[SubmissionResponse])
def list_submissions(
    member: Optional[str] = None,
    status: Optional[str] = None,
    flag: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    if year is None:
        year = date.today().year
    start, end = plan_year_dates(year)
    q = select(Submission).where(
        Submission.service_date >= start,
        Submission.service_date <= end,
    ).order_by(Submission.service_date.desc()).options(_load_options())
    submissions = db.scalars(q).all()

    results = [_to_response(s) for s in submissions]

    if member:
        results = [r for r in results if member.lower() in r.member_name.lower()]
    if status == "matched":
        results = [r for r in results if r.anthem_claim_number is not None]
    elif status == "unmatched":
        results = [r for r in results if r.anthem_claim_number is None]
    if flag:
        results = [r for r in results if any(f.flag == flag for f in r.flags)]

    return results


@router.post("/submissions", response_model=SubmissionResponse, status_code=201)
def create_submission(body: SubmissionCreate, db: Session = Depends(get_db)):
    sub = Submission(
        id=str(uuid.uuid4()),
        **body.model_dump(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(sub)
    db.commit()
    run_matching(db)

    # Re-query with relationships loaded
    sub = db.scalars(
        select(Submission).where(Submission.id == sub.id).options(_load_options())
    ).one()
    return _to_response(sub)


@router.get("/submissions/{id}", response_model=SubmissionResponse)
def get_submission(id: str, db: Session = Depends(get_db)):
    sub = db.scalars(
        select(Submission).where(Submission.id == id).options(_load_options())
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return _to_response(sub)


@router.patch("/submissions/{id}", response_model=SubmissionResponse)
def update_submission(id: str, body: SubmissionUpdate, db: Session = Depends(get_db)):
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(sub, field, value)
    sub.updated_at = datetime.now(timezone.utc)
    db.commit()
    run_matching(db)
    sub = db.scalars(
        select(Submission).where(Submission.id == id).options(_load_options())
    ).one()
    return _to_response(sub)


@router.delete("/submissions/{id}", status_code=204)
def delete_submission(id: str, db: Session = Depends(get_db)):
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.match:
        db.delete(sub.match)
    db.delete(sub)
    db.commit()


@router.post("/submissions/{id}/pdf", status_code=204)
async def upload_pdf(id: str, file: UploadFile, db: Session = Depends(get_db)):
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    key = f"{id}/{file.filename}"
    data = await file.read()
    get_storage().save(key, data)
    sub.pdf_path = key
    sub.updated_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/submissions/{id}/pdf")
def download_pdf(id: str, db: Session = Depends(get_db)):
    sub = db.get(Submission, id)
    if not sub or not sub.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found")
    try:
        data = get_storage().get(sub.pdf_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF file missing from storage")
    return Response(content=data, media_type="application/pdf")
