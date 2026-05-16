from dataclasses import dataclass, field
from datetime import date

from app import config


@dataclass
class Alert:
    flag: str
    severity: str  # "red" | "yellow" | "info"
    details: dict = field(default_factory=dict)


def compute_flags(submission, match=None) -> list[Alert]:
    """Compute alert flags for a submission. match is the Match ORM object or None."""
    alerts: list[Alert] = []
    today = date.today()

    if match is None:
        days = (today - submission.submitted_date).days
        if days > config.MISSING_DAYS:
            alerts.append(Alert("MISSING", "red", {
                "submitted_date": str(submission.submitted_date),
                "days_waiting": days,
            }))
        return alerts

    claim = match.anthem_claim

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
        diff = abs(expected - claim.plan_paid)
        threshold = max(config.UNDERPAID_MIN_CENTS, int(expected * config.UNDERPAID_PCT))
        if diff > threshold:
            alerts.append(Alert("UNDERPAID", "yellow", {
                "expected_cents": expected,
                "plan_paid_cents": claim.plan_paid,
                "diff_cents": diff,
            }))

        if claim.plan_paid == 0 and claim.your_cost > 0:
            alerts.append(Alert("APPROVED_ZERO_PAID", "info", {
                "your_cost_cents": claim.your_cost,
            }))

    return alerts
