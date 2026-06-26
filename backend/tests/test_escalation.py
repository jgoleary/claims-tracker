from datetime import date

from app.alerts import Alert
from app.escalation import build_escalation_message


# ── per-flag templates, claim-specific values plugged in ─────────────────────

def test_generic_mentions_provider_and_service_date(make_submission):
    sub = make_submission(provider_name="Joyful Behavior Therapy", service_date=date(2025, 11, 4))
    msg = build_escalation_message(sub, [])
    assert "Joyful Behavior Therapy" in msg
    assert "November 4, 2025" in msg
    assert "resolv" in msg.lower()


def test_stale_pending(make_submission):
    sub = make_submission(submitted_date=date(2025, 11, 10))
    msg = build_escalation_message(sub, [Alert("STALE_PENDING", "yellow", {"days_pending": 45})])
    assert "45" in msg
    assert "pending" in msg.lower()


def test_missing(make_submission):
    sub = make_submission(submitted_date=date(2025, 11, 10))
    msg = build_escalation_message(
        sub, [Alert("MISSING", "red", {"submitted_date": "2025-11-10", "days_waiting": 60})]
    )
    assert "60" in msg
    assert "November 10, 2025" in msg


def test_denied(make_submission):
    sub = make_submission()
    msg = build_escalation_message(sub, [Alert("DENIED", "red", {})])
    assert "deni" in msg.lower()  # denial / denied


def test_underpaid_includes_dollar_amounts(make_submission):
    sub = make_submission()
    msg = build_escalation_message(sub, [Alert("UNDERPAID", "yellow", {
        "expected_cents": 180_000, "plan_paid_cents": 50_000, "diff_cents": 130_000,
    })])
    assert "$1,800.00" in msg  # expected
    assert "$500.00" in msg    # plan paid
    assert "$1,300.00" in msg  # shortfall


def test_vanished(make_submission):
    sub = make_submission()
    msg = build_escalation_message(sub, [Alert("VANISHED", "red", {})])
    assert "disappear" in msg.lower()


# ── claim number ─────────────────────────────────────────────────────────────

def test_includes_claim_number_when_present(make_submission):
    sub = make_submission()
    msg = build_escalation_message(sub, [], claim_number="CLM-123")
    assert "CLM-123" in msg


def test_omits_claim_number_when_absent(make_submission):
    sub = make_submission()
    msg = build_escalation_message(sub, [])
    assert "claim #" not in msg.lower()


# ── template selection by flag priority ──────────────────────────────────────

def test_denied_takes_priority_over_stale_pending(make_submission):
    sub = make_submission()
    msg = build_escalation_message(sub, [
        Alert("STALE_PENDING", "yellow", {"days_pending": 45}),
        Alert("DENIED", "red", {}),
    ])
    assert "deni" in msg.lower()
    assert "pending for 45" not in msg.lower()


def test_always_returns_nonempty(make_submission):
    sub = make_submission()
    assert build_escalation_message(sub, []).strip()


# ── submission date stated in every template ─────────────────────────────────

def test_every_template_states_submission_date(make_submission):
    sub = make_submission(submitted_date=date(2025, 11, 10))
    flag_sets = [
        [],
        [Alert("DENIED", "red", {})],
        [Alert("VANISHED", "red", {})],
        [Alert("STALE_PENDING", "yellow", {"days_pending": 45})],
        [Alert("MISSING", "red", {"days_waiting": 60})],
        [Alert("UNDERPAID", "yellow", {"expected_cents": 1, "plan_paid_cents": 0, "diff_cents": 1})],
    ]
    for flags in flag_sets:
        msg = build_escalation_message(sub, flags)
        assert "I submitted this claim on November 10, 2025" in msg


def test_submission_date_omitted_when_never_submitted(make_submission):
    sub = make_submission(submitted_date=None)
    msg = build_escalation_message(sub, [])
    assert "I submitted this claim on" not in msg
    assert msg.strip()
