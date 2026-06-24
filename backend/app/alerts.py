from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from app import config


@dataclass
class Alert:
    flag: str
    severity: str  # "red" | "yellow" | "info"
    details: dict = field(default_factory=dict)


def _fmt_ts(dt: datetime) -> str:
    """Format a timestamp for display as a date only — time isn't meaningful here."""
    return dt.date().isoformat()


def compute_flags(submission, match=None, latest_ingest_at: Optional[datetime] = None) -> list[Alert]:
    """Compute alert flags for a submission. match is the Match ORM object or None.

    latest_ingest_at is the timestamp of the most recent claims ingest (the max
    last_seen_at across all anthem_claims). When provided, a matched claim whose
    last_seen_at predates it — i.e. it dropped out of Anthem's latest export — is
    flagged VANISHED.
    """
    alerts: list[Alert] = []
    today = date.today()

    if match is None:
        if submission.submitted_date is None:
            alerts.append(Alert("UNSUBMITTED", "info", {}))
            return alerts
        days = (today - submission.submitted_date).days
        if days > config.MISSING_DAYS:
            alerts.append(Alert("MISSING", "red", {
                "submitted_date": str(submission.submitted_date),
                "days_waiting": days,
            }))
        return alerts

    claim = match.anthem_claim

    if latest_ingest_at is not None and claim.last_seen_at < latest_ingest_at:
        alerts.append(Alert("VANISHED", "red", {
            "last_seen_at": _fmt_ts(claim.last_seen_at),
            "latest_ingest_at": _fmt_ts(latest_ingest_at),
        }))

    if (claim.status == "Pending"
            and claim.received_date is not None
            and (today - claim.received_date).days > config.STALE_PENDING_DAYS):
        alerts.append(Alert("STALE_PENDING", "yellow", {
            "received_date": str(claim.received_date),
            "days_pending": (today - claim.received_date).days,
        }))

    if claim.status == "Denied":
        alerts.append(Alert("DENIED", "red", {}))

    if claim.status == "Approved":
        expected = submission.expected_reimbursement
        underpaid_by = expected - claim.plan_paid
        threshold = max(config.UNDERPAID_MIN_CENTS, int(expected * config.UNDERPAID_PCT))
        if underpaid_by > threshold:
            alerts.append(Alert("UNDERPAID", "yellow", {
                "expected_cents": expected,
                "plan_paid_cents": claim.plan_paid,
                "diff_cents": underpaid_by,
            }))

        overpaid_by = claim.plan_paid - expected
        if overpaid_by > threshold:
            alerts.append(Alert("OVERPAID", "info", {
                "expected_cents": expected,
                "plan_paid_cents": claim.plan_paid,
                "diff_cents": overpaid_by,
            }))

        if claim.plan_paid == 0 and claim.your_cost > 0 and submission.expected_reimbursement > 0:
            alerts.append(Alert("APPROVED_ZERO_PAID", "info", {
                "your_cost_cents": claim.your_cost,
            }))

    return alerts
