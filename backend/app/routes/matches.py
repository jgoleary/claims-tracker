from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.matching import classify_matches, load_matching_inputs, normalize
from app.models import AnthemClaim, Match, ProviderAlias, Submission
from app.routes.anthem_claims import _to_response as _claim_to_response
from app.routes.submissions import _load_options, _to_response as _sub_to_response
from app.schemas import MatchCreate, MatchSuggestion

router = APIRouter()


@router.get("/matches/suggestions", response_model=list[MatchSuggestion])
def get_suggestions(db: Session = Depends(get_db)):
    # Suggestions are computed on read (not stored) via the same classifier that
    # run_matching() uses to count them at ingest — see matching.classify_matches.
    # We only report the "suggestion" outcomes; "auto" ones are (or will be) matched.
    unmatched_subs = db.scalars(
        select(Submission)
        .where(~exists().where(Match.submission_id == Submission.id))
        .options(*_load_options())
    ).all()

    submissions, unmatched_claims, aliases = load_matching_inputs(
        db, submissions=unmatched_subs
    )

    return [
        MatchSuggestion(
            submission=_sub_to_response(outcome.submission),
            candidates=[_claim_to_response(c) for c in outcome.claims],
        )
        for outcome in classify_matches(submissions, unmatched_claims, aliases)
        if outcome.kind == "suggestion"
    ]


@router.post("/matches", status_code=201)
def create_match(body: MatchCreate, db: Session = Depends(get_db)):
    if db.get(Match, body.submission_id):
        raise HTTPException(status_code=409, detail="Submission already matched")

    existing_for_claim = db.scalars(
        select(Match).where(Match.anthem_claim_number == body.anthem_claim_number)
    ).first()
    if existing_for_claim:
        raise HTTPException(status_code=409, detail="Anthem claim already matched")

    match = Match(
        submission_id=body.submission_id,
        anthem_claim_number=body.anthem_claim_number,
        match_type=body.match_type,
        matched_at=datetime.now(timezone.utc),
        confirmed_at=datetime.now(timezone.utc) if body.match_type == "confirmed" else None,
    )
    db.add(match)

    # Learn provider alias when confirming a suggestion
    if body.match_type == "confirmed":
        sub = db.get(Submission, body.submission_id)
        claim = db.get(AnthemClaim, body.anthem_claim_number)
        if sub and claim:
            canonical = normalize(sub.provider_name)
            anthem_name = normalize(claim.provider_name)
            if canonical != anthem_name:
                existing_alias = db.scalars(
                    select(ProviderAlias).where(
                        ProviderAlias.canonical_name == canonical,
                        ProviderAlias.anthem_name == anthem_name,
                    )
                ).first()
                if not existing_alias:
                    db.add(ProviderAlias(canonical_name=canonical, anthem_name=anthem_name))

    db.commit()
    return {"submission_id": body.submission_id, "anthem_claim_number": body.anthem_claim_number}


@router.delete("/matches/{submission_id}", status_code=204)
def delete_match(submission_id: str, db: Session = Depends(get_db)):
    match = db.get(Match, submission_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    db.delete(match)
    db.commit()
