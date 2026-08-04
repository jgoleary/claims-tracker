"""Manual resolution of submissions, and the sweep that undoes it.

Resolving a submission silences its flags (see alerts.compute_flags), which is what you
want for something accurate but not actionable — an overpayment, say. It is not meant to
bury a *new* problem, so a resolution only holds while nothing new is wrong: every claims
ingest re-checks each resolved submission against the flag set that was current when it
was resolved, and clears the resolution if a flag type appears that wasn't in that
snapshot.
"""

from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.alerts import Alert, compute_raw_flags
from app.models import AnthemClaim, Match, Submission


def snapshot_flags(flags: Iterable[Alert]) -> str:
    """Serialize a flag set for storage in Submission.resolved_flags."""
    return ",".join(sorted({f.flag for f in flags}))


def parse_snapshot(snapshot: Optional[str]) -> set[str]:
    """Inverse of snapshot_flags. An empty or missing snapshot is an empty set, so a
    submission resolved while it had no flags reopens as soon as it grows one."""
    return {f for f in (snapshot or "").split(",") if f}


def reopen_resolved(db: Session) -> list[str]:
    """Clear the resolution on every resolved submission that has picked up a flag type
    it didn't have when it was resolved. Returns the ids that were reopened.

    Called after each claims ingest — the point at which new Anthem data arrives.
    """
    latest_ingest = db.scalar(select(func.max(AnthemClaim.last_seen_at)))
    resolved = db.scalars(
        select(Submission)
        .where(Submission.resolved_at.is_not(None))
        .options(selectinload(Submission.match).selectinload(Match.anthem_claim))
    ).all()

    reopened: list[str] = []
    for sub in resolved:
        flags = compute_raw_flags(sub, sub.match, latest_ingest_at=latest_ingest)
        if {f.flag for f in flags} - parse_snapshot(sub.resolved_flags):
            sub.resolved_at = None
            sub.resolved_flags = None
            reopened.append(sub.id)

    if reopened:
        db.commit()
    return reopened
