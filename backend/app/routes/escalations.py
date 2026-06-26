from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import automation
from app.alerts import compute_flags
from app.database import get_db
from app.escalation import build_escalation_message
from app.models import Match, Submission
from app.routes.submissions import latest_ingest_at
from app.schemas import EscalationDraft, EscalationRun, EscalationStatus

router = APIRouter()


@router.post("/submissions/{id}/escalate/draft", response_model=EscalationDraft)
def escalate_draft(id: str, db: Session = Depends(get_db)):
    sub = db.scalars(
        select(Submission)
        .where(Submission.id == id)
        .options(selectinload(Submission.match).selectinload(Match.anthem_claim))
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    flags = compute_flags(sub, sub.match, latest_ingest_at=latest_ingest_at(db))
    claim_number = sub.match.anthem_claim_number if sub.match else None
    return EscalationDraft(message=build_escalation_message(sub, flags, claim_number=claim_number))


@router.post("/submissions/{id}/escalate/run", status_code=202)
def escalate_run(id: str, body: EscalationRun, db: Session = Depends(get_db)):
    sub = db.get(Submission, id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    started = automation.run_escalation(
        submission_id=sub.id,
        member_name=sub.member_name,
        provider_name=sub.provider_name,
        service_date=sub.service_date.isoformat(),
        message=body.message,
        pdf_key=sub.pdf_path,
    )
    if not started:
        return {"detail": "Automation already running"}
    return {"detail": "Escalation started"}


@router.get("/escalations/status", response_model=EscalationStatus)
def escalation_status():
    state = automation.get_escalation_status()
    return EscalationStatus(
        status=state["status"],
        submission_id=state.get("submission_id"),
        last_run_at=state.get("last_run_at"),
        summary=state.get("summary"),
    )
