"""Build an Included Health escalation message for a submission.

The message is built template-first so escalation works with **no Anthropic key**:
`build_template_message` is a pure function that plugs claim-specific values into
per-flag sentences. When a key is configured, `generate_escalation_message`
refines that draft with Claude; on any failure it falls back to the template.
"""
import os
from datetime import date
from typing import Optional

import anthropic

from app import credentials
from app.alerts import Alert
from app.schemas import EscalationDraft

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 512


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _long_date(d: Optional[date]) -> Optional[str]:
    if d is None:
        return None
    return f"{d:%B} {d.day}, {d.year}"


def build_template_message(submission, flags: list[Alert]) -> str:
    """Compose a first-person escalation paragraph from the submission's flags.

    Pure: no I/O. Opens with provider + service date, adds one sentence per
    actionable flag with claim-specific values plugged in, closes with a request
    for help. Always returns a non-empty string.
    """
    provider = submission.provider_name
    svc = _long_date(submission.service_date)
    by_flag = {f.flag: f for f in flags}

    sentences = [
        f"I'm writing to follow up on an out-of-network claim for {provider} "
        f"with a date of service of {svc}."
    ]

    if "STALE_PENDING" in by_flag:
        days = by_flag["STALE_PENDING"].details.get("days_pending")
        submitted = _long_date(submission.submitted_date) or "the date I submitted it"
        sentences.append(
            f"I submitted this claim on {submitted} and it has been pending for "
            f"{days} days without resolution."
        )

    if "MISSING" in by_flag:
        days = by_flag["MISSING"].details.get("days_waiting")
        submitted = _long_date(submission.submitted_date) or "some time ago"
        sentences.append(
            f"I submitted this claim on {submitted} ({days} days ago) but it still "
            f"has not appeared in my claims."
        )

    if "DENIED" in by_flag:
        sentences.append("This claim was denied and I would like it reviewed.")

    if "UNDERPAID" in by_flag:
        d = by_flag["UNDERPAID"].details
        sentences.append(
            f"This claim was approved but reimbursed {_dollars(d.get('plan_paid_cents', 0))} "
            f"versus the {_dollars(d.get('expected_cents', 0))} I expected — a shortfall of "
            f"{_dollars(d.get('diff_cents', 0))}."
        )

    if "VANISHED" in by_flag:
        sentences.append(
            "This claim previously appeared in my Anthem account and has since "
            "disappeared from my claims."
        )

    # No flag produced a specific sentence — keep the message actionable.
    if len(sentences) == 1:
        sentences.append(
            "I need help resolving this claim and would appreciate your assistance."
        )

    sentences.append("Could you please help me get this resolved? Thank you.")
    return " ".join(sentences)


def _ai_prompt(template: str, flags: list[Alert]) -> str:
    flag_list = ", ".join(f.flag for f in flags) or "none"
    return (
        "You are helping a patient escalate a health-insurance claim to a member-support "
        "advocate (Included Health). Rewrite the draft below into one polite, concise, "
        "first-person paragraph (under 2000 characters) that explains the situation and "
        "asks for help. Keep every specific fact (dates, dollar amounts, provider name). "
        "Return only the message text, with no preamble or sign-off line.\n\n"
        f"Flags: {flag_list}\n"
        f"Draft: {template}"
    )


def generate_escalation_message(submission, flags: list[Alert]) -> EscalationDraft:
    """Return an escalation message — template-based, AI-refined when a key is set.

    Never raises. A non-empty `message` is always returned: the template when no
    key is configured or the AI call fails, the AI text otherwise.
    """
    template = build_template_message(submission, flags)

    key = credentials.get_anthropic_key() or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return EscalationDraft(configured=False, source="template", message=template)

    try:
        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": _ai_prompt(template, flags)}],
        )
        text = next(
            (b.text for b in message.content if getattr(b, "type", None) == "text"), ""
        ).strip()
        if not text:
            raise ValueError("empty response from Claude")
    except Exception as e:  # noqa: BLE001 — fall back to the template
        return EscalationDraft(configured=True, source="template", error=str(e), message=template)

    return EscalationDraft(configured=True, source="ai", message=text)
