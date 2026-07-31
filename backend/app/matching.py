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


def _first_name(s: str) -> str:
    """Normalized first name only. Anthem claims store first-name-only patient
    names, while submissions may hold a full member name — compare on first name
    so the two still link."""
    parts = normalize(s).split(' ')
    return parts[0] if parts and parts[0] else ''


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


@dataclass
class MatchOutcome:
    """One submission's classification against the unmatched-claim pool.

    kind == "auto":       ``claims`` holds the single confident provider match.
    kind == "suggestion": ``claims`` holds the candidates needing human review
                          (either an ambiguous multi-provider match, or a
                          member+date match with no provider match).
    """
    submission: Submission
    kind: str
    claims: list[AnthemClaim]


def load_matching_inputs(db: Session, submissions=None):
    """Load the (unmatched submissions, unmatched claims, aliases) triple that
    the matcher operates on. Callers that need eager-loaded submissions (e.g.
    for serialization) may pass their own ``submissions`` list."""
    if submissions is None:
        submissions = db.scalars(
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
    return submissions, unmatched_claims, aliases


def classify_matches(submissions, unmatched_claims, aliases):
    """Yield a MatchOutcome for each submission that has ≥1 candidate claim.

    A claim auto-matched to an earlier submission is dropped from later
    submissions' candidate pools, so one claim is never offered twice in a pass.

    Single source of truth for the candidate filter and tiering — shared by
    run_matching() (persists auto-matches, counts suggestions) and the
    /matches/suggestions endpoint (surfaces those same suggestions). Keep them
    consuming this so the two can't drift.
    """
    claimed: set[str] = set()
    for submission in submissions:
        member_first = _first_name(submission.member_name)
        candidates = [
            c for c in unmatched_claims
            if c.claim_number not in claimed
            and c.service_date == submission.service_date
            and _first_name(c.patient_name) == member_first
        ]
        if not candidates:
            continue

        tier1 = [
            c for c in candidates
            if _provider_matches(submission.provider_name, c.provider_name, aliases)
        ]

        if len(tier1) == 1:
            claimed.add(tier1[0].claim_number)
            yield MatchOutcome(submission, "auto", [tier1[0]])
        elif len(tier1) > 1:
            yield MatchOutcome(submission, "suggestion", tier1)
        else:
            yield MatchOutcome(submission, "suggestion", candidates)


def run_matching(db: Session) -> MatchResult:
    result = MatchResult()
    submissions, unmatched_claims, aliases = load_matching_inputs(db)

    for outcome in classify_matches(submissions, unmatched_claims, aliases):
        sub_id = outcome.submission.id
        if outcome.kind == "auto":
            claim = outcome.claims[0]
            db.add(Match(
                submission_id=sub_id,
                anthem_claim_number=claim.claim_number,
                match_type="auto",
            ))
            result.auto_matched.append((sub_id, claim.claim_number))
        else:
            result.suggestions.append((sub_id, [c.claim_number for c in outcome.claims]))

    db.commit()
    return result
