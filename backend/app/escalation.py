"""Build an Included Health escalation message for a submission.

No runtime LLM call: the wording barely changes between escalations, so instead
of asking Claude every time we keep one fixed, Claude-authored template per
escalation type (selected by the submission's dominant flag) and plug in the
claim-specific values. Always returns a non-empty, ready-to-send paragraph.
"""
from datetime import date
from typing import Optional

from app.alerts import Alert

# One template per escalation type. Placeholders: {provider}, {service_date},
# {claim_ref}, {submitted} (common to all); plus flag-specific {days_pending},
# {days_waiting}, {plan_paid}, {expected}, {expected_note}, {diff}. {submitted}
# expands to " I submitted this claim on <date>." (or "" when the claim was never
# submitted); {expected_note} to " I had expected reimbursement of <amount>."
_GENERIC = (
    "I'm following up on a member submitted claim for {provider} (date of service "
    "{service_date}{claim_ref}).{submitted} I would appreciate your help getting it "
    "fully processed and resolved. Please let me know if you need any additional "
    "information from me."
)

_TEMPLATES = {
    "DENIED": (
        "I'm contesting the denial of a member submitted claim for {provider} (date "
        "of service {service_date}{claim_ref}).{submitted} I believe this claim should "
        "be covered under my plan benefits, and I'd like help understanding the reason "
        "for the denial and getting it reviewed. Please let me know what additional "
        "information would support an appeal."
    ),
    "VANISHED": (
        "I'm following up on a member submitted claim for {provider} (date of service "
        "{service_date}{claim_ref}).{submitted} This claim previously appeared in my "
        "Anthem account but has since disappeared from my claims, and I'm concerned "
        "it may have been dropped. Could you help confirm its status and make sure "
        "it's still being processed? I'm happy to provide any documentation you need."
    ),
    "MISSING": (
        "I'm following up on a member submitted claim for {provider} (date of service "
        "{service_date}{claim_ref}).{submitted} That was {days_waiting} days ago, and "
        "it still hasn't appeared in my claims. Could you help confirm it was received "
        "and make sure it gets processed? I'm happy to resend any documentation you "
        "need."
    ),
    "STALE_PENDING": (
        "I'm following up on a member submitted claim for {provider} (date of service "
        "{service_date}{claim_ref}).{submitted} It has now been pending for "
        "{days_pending} days without a resolution. I'd appreciate your help finding "
        "out why it's delayed and getting it processed. Please let me know if you "
        "need anything further from me."
    ),
    "UNDERPAID": (
        "I'm following up on a member submitted claim for {provider} (date of service "
        "{service_date}{claim_ref}).{submitted} The claim was approved but reimbursed "
        "{plan_paid} versus the {expected} I expected — a shortfall of {diff}. I'd "
        "appreciate your help reviewing how it was processed and correcting the "
        "reimbursement if it was underpaid. Please let me know if you need anything "
        "further."
    ),
    "INN_EXCEPTION_NOT_APPLIED": (
        "I'm following up on a member submitted claim for {provider} (date of service "
        "{service_date}{claim_ref}) that has an approved in-network exception."
        "{submitted} Anthem shows the claim as approved, but the plan paid {plan_paid} "
        "toward it.{expected_note} I believe the claim was processed as out-of-network "
        "when it should have been processed as in-network."
    ),
}

# Which template wins when a submission carries several flags (most actionable first).
_PRIORITY = [
    "DENIED", "VANISHED", "MISSING", "STALE_PENDING",
    "INN_EXCEPTION_NOT_APPLIED", "UNDERPAID",
]


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _long_date(d: Optional[date]) -> Optional[str]:
    if d is None:
        return None
    return f"{d:%B} {d.day}, {d.year}"


def _inn_exception_not_applied(submission, claim) -> bool:
    """True when an in-network-exception claim was approved but paid nothing.

    That combination almost always means Anthem adjudicated the claim at the
    out-of-network benefit level instead of honoring the exception, so the
    escalation should propose that as the reason.
    """
    return (
        claim is not None
        and submission.network_treatment == "in_network_exception"
        and claim.status == "Approved"
        and claim.plan_paid == 0
    )


def build_escalation_message(submission, flags: list[Alert],
                             claim_number: str | None = None, claim=None) -> str:
    """Select the template for the submission's dominant flag and fill it in.

    `claim` is the matched AnthemClaim (or None); it is only read for conditions
    that aren't expressible as alert flags. Pure (no I/O) and never raises — a
    non-empty paragraph is always returned.
    """
    by_flag = {f.flag: f for f in flags}
    if _inn_exception_not_applied(submission, claim):
        by_flag["INN_EXCEPTION_NOT_APPLIED"] = Alert(
            "INN_EXCEPTION_NOT_APPLIED", "yellow",
            {"plan_paid_cents": 0, "expected_cents": submission.expected_reimbursement},
        )
    chosen = next((f for f in _PRIORITY if f in by_flag), None)
    template = _TEMPLATES.get(chosen, _GENERIC)

    details = by_flag[chosen].details if chosen else {}
    submitted = _long_date(submission.submitted_date)
    expected_cents = details.get("expected_cents", 0)
    values = {
        "provider": submission.provider_name,
        "service_date": _long_date(submission.service_date),
        "claim_ref": f"; Anthem claim #{claim_number}" if claim_number else "",
        "submitted": f" I submitted this claim on {submitted}." if submitted else "",
        "days_pending": details.get("days_pending", ""),
        "days_waiting": details.get("days_waiting", ""),
        "plan_paid": _dollars(details.get("plan_paid_cents", 0)),
        "expected": _dollars(expected_cents),
        "expected_note": (
            f" I had expected reimbursement of {_dollars(expected_cents)}."
            if expected_cents else ""
        ),
        "diff": _dollars(details.get("diff_cents", 0)),
    }
    return template.format(**values)
