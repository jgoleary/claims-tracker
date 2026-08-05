from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import automation
from app.database import get_db
from app.models import Submission
from app.schemas import ClaimFilingStatus

router = APIRouter()


@router.post("/submissions/{id}/file-with-anthem/run", status_code=202)
def file_with_anthem_run(id: str, db: Session = Depends(get_db)):
    """Drive Anthem's claim wizard for this submission. The wizard is only taken
    as far as the upload step — the user finishes and confirms it themselves."""
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if not sub.pdf_path:
        raise HTTPException(status_code=400, detail="Submission has no PDF to upload")
    started = automation.run_claim_filing(
        submission_id=sub.id,
        member_name=sub.member_name,
        pdf_key=sub.pdf_path,
    )
    if not started:
        return {"detail": "Automation already running"}
    return {"detail": "Claim filing started"}


@router.get("/claim-filing/status", response_model=ClaimFilingStatus)
def claim_filing_status():
    state = automation.get_claim_filing_status()
    return ClaimFilingStatus(
        status=state["status"],
        submission_id=state.get("submission_id"),
        last_run_at=state.get("last_run_at"),
        summary=state.get("summary"),
    )
