import json
from datetime import date
from unittest.mock import MagicMock

from app import extraction


def _fake_client(payload: dict):
    msg = MagicMock()
    msg.content = [MagicMock(type="text", text=json.dumps(payload))]
    client = MagicMock()
    client.messages.create.return_value = msg
    return client


def test_not_configured_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is False


def test_success_maps_fields(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = _fake_client({
        "member_name": "Nolan OLeary",
        "provider_name": "Citrus Speech",
        "first_service_date": "2026-05-06",
        "amount_billed": "$570.00",
    })
    monkeypatch.setattr(extraction.anthropic, "Anthropic", lambda *a, **k: client)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert result.error is None
    assert result.member_name == "Nolan OLeary"
    assert result.provider_name == "Citrus Speech"
    assert result.first_service_date == date(2026, 5, 6)
    assert result.amount_billed_cents == 57000


def test_blank_fields_become_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = _fake_client({
        "member_name": "",
        "provider_name": "",
        "first_service_date": "",
        "amount_billed": "",
    })
    monkeypatch.setattr(extraction.anthropic, "Anthropic", lambda *a, **k: client)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert result.member_name is None
    assert result.amount_billed_cents is None
    assert result.first_service_date is None


def test_malformed_values_degrade_to_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = _fake_client({
        "member_name": "Nolan OLeary",
        "provider_name": "Citrus Speech",
        "first_service_date": "not-a-date",
        "amount_billed": "free of charge",
    })
    monkeypatch.setattr(extraction.anthropic, "Anthropic", lambda *a, **k: client)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert result.error is None
    assert result.first_service_date is None
    assert result.amount_billed_cents is None
    assert result.member_name == "Nolan OLeary"


def test_api_error_is_captured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    monkeypatch.setattr(extraction.anthropic, "Anthropic", lambda *a, **k: client)
    result = extraction.extract_submission_fields(b"%PDF-1.4 fake")
    assert result.configured is True
    assert "boom" in result.error
    assert result.member_name is None
