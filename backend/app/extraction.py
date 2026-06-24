import base64
import json
import os
from typing import Optional

import anthropic

from app.ingest import _parse_date, _parse_money
from app.schemas import ExtractionResult

_MODEL = "claude-sonnet-4-6"

_SCHEMA = {
    "type": "object",
    "properties": {
        "member_name": {"type": "string", "description": "Patient or member full name; empty string if not found"},
        "provider_name": {"type": "string", "description": "Provider, practice, or facility name; empty string if not found"},
        "first_service_date": {"type": "string", "description": "Earliest date of service if several appear, ISO YYYY-MM-DD preferred; empty string if not found"},
        "amount_billed": {"type": "string", "description": "Total amount billed including the dollar sign, e.g. \"$570.00\"; empty string if not found"},
    },
    "required": ["member_name", "provider_name", "first_service_date", "amount_billed"],
    "additionalProperties": False,
}

_PROMPT = (
    "This is a medical claim or superbill PDF. Extract the member name, the provider "
    "name, the earliest date of service (if several are listed), and the total amount "
    "billed, and return them in the required JSON format. If a field cannot be "
    "determined, use an empty string."
)


def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    return s or None


def extract_submission_fields(pdf_bytes: bytes) -> ExtractionResult:
    """Send a claim PDF to Claude and extract submission fields.

    Returns configured=False when no ANTHROPIC_API_KEY is set, and
    configured=True with an error string when the call or parse fails. Never
    raises — callers fall back to manual entry.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ExtractionResult(configured=False)

    try:
        client = anthropic.Anthropic()
        b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        message = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        )
        text = next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001 — degrade gracefully to manual entry
        return ExtractionResult(configured=True, error=str(e))

    billed_raw = _clean(data.get("amount_billed"))
    date_raw = _clean(data.get("first_service_date"))
    try:
        service_date = _parse_date(date_raw) if date_raw else None
    except ValueError:
        service_date = None

    return ExtractionResult(
        configured=True,
        member_name=_clean(data.get("member_name")),
        provider_name=_clean(data.get("provider_name")),
        first_service_date=service_date,
        amount_billed_cents=_parse_money(billed_raw) if billed_raw else None,
    )
