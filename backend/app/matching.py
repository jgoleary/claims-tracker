import re
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import select, exists

from app.models import Submission, AnthemClaim, Match, ProviderAlias


def normalize(s: str) -> str:
    """Lowercase, collapse whitespace, strip non-alphanumeric except spaces."""
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return s


def _provider_matches(
    sub_provider: str,
    claim_provider: str,
    alias_pairs: list[tuple[str, str]],
) -> bool:
    """True if providers match by exact name, prefix, or known alias."""
    n_sub = normalize(sub_provider)
    n_claim = normalize(claim_provider)

    if n_sub == n_claim:
        return True
    if n_sub.startswith(n_claim) or n_claim.startswith(n_sub):
        return True
    for canonical, anthem in alias_pairs:
        if canonical == n_sub and anthem == n_claim:
            return True
    return False


@dataclass
class MatchResult:
    auto_matched: list[tuple[str, str]] = field(default_factory=list)
    suggestions: list[tuple[str, list[str]]] = field(default_factory=list)


def run_matching(db: Session) -> MatchResult:
    result = MatchResult()

    unmatched_submissions = db.scalars(
        select(Submission).where(
            ~exists().where(Match.submission_id == Submission.id)
        )
    ).all()

    unmatched_claims = db.scalars(
        select(AnthemClaim).where(
            ~exists().where(Match.anthem_claim_number == AnthemClaim.claim_number)
        )
    ).all()

    aliases = [
        (a.canonical_name, a.anthem_name)
        for a in db.scalars(select(ProviderAlias)).all()
    ]

    newly_matched_claims: set[str] = set()

    for submission in unmatched_submissions:
        norm_member = normalize(submission.member_name)

        candidates = [
            c for c in unmatched_claims
            if c.claim_number not in newly_matched_claims
            and c.service_date == submission.service_date
            and normalize(c.patient_name) == norm_member
        ]

        if not candidates:
            continue

        tier1 = [
            c for c in candidates
            if _provider_matches(submission.provider_name, c.provider_name, aliases)
        ]

        if len(tier1) == 1:
            db.add(Match(
                submission_id=submission.id,
                anthem_claim_number=tier1[0].claim_number,
                match_type="auto",
            ))
            newly_matched_claims.add(tier1[0].claim_number)
            result.auto_matched.append((submission.id, tier1[0].claim_number))
        elif len(tier1) > 1:
            result.suggestions.append((submission.id, [c.claim_number for c in tier1]))
        else:
            result.suggestions.append((submission.id, [c.claim_number for c in candidates]))

    db.commit()
    return result
