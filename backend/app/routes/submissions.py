import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.alerts import compute_flags, compute_raw_flags
from app.config import plan_year_dates
from app.database import get_db
from app.extraction import extract_submission_fields
from app.matching import run_matching
from app.models import AnthemClaim, Match, Submission
from app.resolution import snapshot_flags
from app.schemas import (
    AlertOut, ExtractionResult, SubmissionCreate, SubmissionRef,
    SubmissionResponse, SubmissionUpdate, SupersedeRequest,
)
from app.storage import get_storage

router = APIRouter()


def latest_ingest_at(db: Session) -> Optional[datetime]:
    """Timestamp of the most recent claims ingest (max last_seen_at across all
    anthem_claims). Used to detect claims that dropped out of Anthem's export."""
    return db.scalar(select(func.max(AnthemClaim.last_seen_at)))


def _to_response(submission: Submission, latest_ingest: Optional[datetime] = None) -> SubmissionResponse:
    match = submission.match
    flags = compute_flags(submission, match, latest_ingest_at=latest_ingest)
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
        escalated_at=submission.escalated_at,
        resolved_at=submission.resolved_at,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
        anthem_claim_number=match.anthem_claim_number if match else None,
        anthem_claim_status=match.anthem_claim.status if match and match.anthem_claim else None,
        anthem_plan_paid=match.anthem_claim.plan_paid if match and match.anthem_claim else None,
        superseded_by=SubmissionRef.model_validate(submission.superseded_by) if submission.superseded_by else None,
        supersedes=[SubmissionRef.model_validate(s) for s in submission.supersedes],
        flags=[AlertOut(flag=a.flag, severity=a.severity, details=a.details) for a in flags],
    )


def _load_options():
    return (
        selectinload(Submission.match).selectinload(Match.anthem_claim),
        selectinload(Submission.superseded_by),
        selectinload(Submission.supersedes),
    )


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
    ).order_by(Submission.service_date.desc()).options(*_load_options())
    submissions = db.scalars(q).all()

    latest_ingest = latest_ingest_at(db)
    results = [_to_response(s, latest_ingest) for s in submissions]

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
        select(Submission).where(Submission.id == sub.id).options(*_load_options())
    ).one()
    return _to_response(sub, latest_ingest_at(db))


@router.get("/submissions/{id}", response_model=SubmissionResponse)
def get_submission(id: str, db: Session = Depends(get_db)):
    sub = db.scalars(
        select(Submission).where(Submission.id == id).options(*_load_options())
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return _to_response(sub, latest_ingest_at(db))


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
        select(Submission).where(Submission.id == id).options(*_load_options())
    ).one()
    return _to_response(sub, latest_ingest_at(db))


@router.post("/submissions/{id}/supersede", response_model=SubmissionResponse)
def supersede_submission(id: str, body: SupersedeRequest, db: Session = Depends(get_db)):
    """Deprecate a submission by pointing it at the submission that follows it up.
    A superseded submission raises no alerts and drops out of the default views."""
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if body.superseded_by_id == id:
        raise HTTPException(status_code=400, detail="A submission cannot supersede itself")
    successor = db.get(Submission, body.superseded_by_id)
    if not successor:
        raise HTTPException(status_code=404, detail="Successor submission not found")
    sub.superseded_by_id = body.superseded_by_id
    sub.updated_at = datetime.now(timezone.utc)
    db.commit()
    sub = db.scalars(
        select(Submission).where(Submission.id == id).options(*_load_options())
    ).one()
    return _to_response(sub, latest_ingest_at(db))


@router.delete("/submissions/{id}/supersede", response_model=SubmissionResponse)
def unsupersede_submission(id: str, db: Session = Depends(get_db)):
    """Undo a deprecation — clear the supersede pointer."""
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    sub.superseded_by_id = None
    sub.updated_at = datetime.now(timezone.utc)
    db.commit()
    sub = db.scalars(
        select(Submission).where(Submission.id == id).options(*_load_options())
    ).one()
    return _to_response(sub, latest_ingest_at(db))


@router.post("/submissions/{id}/resolve", response_model=SubmissionResponse)
def resolve_submission(id: str, db: Session = Depends(get_db)):
    """Manually close out a submission whose flags are accurate but no longer actionable
    (e.g. an overpayment). A resolved submission raises no alerts and drops out of the
    default views. The flags it has right now are snapshotted, so a later ingest that
    raises a flag type it didn't have reopens it (see app.resolution)."""
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    flags = compute_raw_flags(sub, sub.match, latest_ingest_at=latest_ingest_at(db))
    sub.resolved_at = datetime.now(timezone.utc)
    sub.resolved_flags = snapshot_flags(flags)
    sub.updated_at = datetime.now(timezone.utc)
    db.commit()
    sub = db.scalars(
        select(Submission).where(Submission.id == id).options(*_load_options())
    ).one()
    return _to_response(sub, latest_ingest_at(db))


@router.delete("/submissions/{id}/resolve", response_model=SubmissionResponse)
def unresolve_submission(id: str, db: Session = Depends(get_db)):
    """Undo a manual resolution — the submission's flags come back."""
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    sub.resolved_at = None
    sub.resolved_flags = None
    sub.updated_at = datetime.now(timezone.utc)
    db.commit()
    sub = db.scalars(
        select(Submission).where(Submission.id == id).options(*_load_options())
    ).one()
    return _to_response(sub, latest_ingest_at(db))


@router.delete("/submissions/{id}", status_code=204)
def delete_submission(id: str, db: Session = Depends(get_db)):
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.match:
        db.delete(sub.match)
    # Clear any pointers to this submission so no dangling supersede link is left behind.
    for orphan in db.scalars(select(Submission).where(Submission.superseded_by_id == id)).all():
        orphan.superseded_by_id = None
    db.delete(sub)
    db.commit()


@router.post("/submissions/extract", response_model=ExtractionResult)
async def extract_submission(file: UploadFile):
    data = await file.read()
    return extract_submission_fields(data)


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
