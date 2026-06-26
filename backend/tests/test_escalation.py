from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.alerts import Alert
from app.escalation import build_template_message, generate_escalation_message


# ── build_template_message (pure, always works) ──────────────────────────────

def test_template_always_mentions_provider_and_service_date(make_submission):
    sub = make_submission(provider_name="Joyful Behavior Therapy", service_date=date(2025, 11, 4))
    msg = build_template_message(sub, [])
    assert "Joyful Behavior Therapy" in msg
    assert "November 4, 2025" in msg


def test_template_generic_when_no_actionable_flags(make_submission):
    sub = make_submission()
    msg = build_template_message(sub, [])
    assert msg.strip()
    assert "resolv" in msg.lower()  # asks for help resolving


def test_template_stale_pending(make_submission):
    sub = make_submission(submitted_date=date(2025, 11, 10))
    msg = build_template_message(sub, [Alert("STALE_PENDING", "yellow", {"days_pending": 45})])
    assert "45" in msg
    assert "pending" in msg.lower()


def test_template_missing(make_submission):
    sub = make_submission(submitted_date=date(2025, 11, 10))
    msg = build_template_message(
        sub, [Alert("MISSING", "red", {"submitted_date": "2025-11-10", "days_waiting": 60})]
    )
    assert "60" in msg
    assert "November 10, 2025" in msg


def test_template_denied(make_submission):
    sub = make_submission()
    msg = build_template_message(sub, [Alert("DENIED", "red", {})])
    assert "denied" in msg.lower()


def test_template_underpaid_includes_dollar_amounts(make_submission):
    sub = make_submission()
    msg = build_template_message(sub, [Alert("UNDERPAID", "yellow", {
        "expected_cents": 180_000, "plan_paid_cents": 50_000, "diff_cents": 130_000,
    })])
    assert "$1,800.00" in msg  # expected
    assert "$500.00" in msg    # plan paid
    assert "$1,300.00" in msg  # shortfall


def test_template_vanished(make_submission):
    sub = make_submission()
    msg = build_template_message(sub, [Alert("VANISHED", "red", {})])
    assert "disappear" in msg.lower()


# ── generate_escalation_message (template-first, optional Claude refine) ──────

def test_generate_without_key_returns_template(make_submission, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("app.escalation.credentials.get_anthropic_key", lambda: None)
    sub = make_submission()
    result = generate_escalation_message(sub, [Alert("DENIED", "red", {})])
    assert result.configured is False
    assert result.source == "template"
    assert result.message == build_template_message(sub, [Alert("DENIED", "red", {})])
    assert result.message.strip()


def test_generate_with_key_uses_ai(make_submission, monkeypatch):
    monkeypatch.setattr("app.escalation.credentials.get_anthropic_key", lambda: "sk-test")
    fake_block = MagicMock(type="text", text="AI refined message.")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = MagicMock(content=[fake_block])
    with patch("app.escalation.anthropic.Anthropic", return_value=fake_client):
        sub = make_submission()
        result = generate_escalation_message(sub, [Alert("DENIED", "red", {})])
    assert result.configured is True
    assert result.source == "ai"
    assert result.message == "AI refined message."


def test_generate_falls_back_to_template_on_api_error(make_submission, monkeypatch):
    monkeypatch.setattr("app.escalation.credentials.get_anthropic_key", lambda: "sk-test")
    with patch("app.escalation.anthropic.Anthropic", side_effect=RuntimeError("boom")):
        sub = make_submission()
        flags = [Alert("DENIED", "red", {})]
        result = generate_escalation_message(sub, flags)
    assert result.configured is True
    assert result.source == "template"
    assert result.error is not None
    assert result.message == build_template_message(sub, flags)
