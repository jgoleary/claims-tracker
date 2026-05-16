from datetime import date, timedelta
from unittest.mock import MagicMock
import pytest

from app.alerts import compute_flags
from app import config


def _make_submission(submitted_date=None, expected_reimbursement=180_000, network_treatment="out_of_network"):
    s = MagicMock()
    s.submitted_date = submitted_date or (date.today() - timedelta(days=5))
    s.expected_reimbursement = expected_reimbursement
    s.network_treatment = network_treatment
    return s


def _make_match(status="Pending", plan_paid=0, your_cost=0, received_date=None, plan_paid_val=None):
    claim = MagicMock()
    claim.status = status
    claim.plan_paid = plan_paid_val if plan_paid_val is not None else plan_paid
    claim.your_cost = your_cost
    claim.received_date = received_date
    match = MagicMock()
    match.anthem_claim = claim
    return match


class TestComputeFlags:
    def test_no_flags_recent_unmatched(self):
        sub = _make_submission(submitted_date=date.today() - timedelta(days=5))
        assert compute_flags(sub, match=None) == []

    def test_missing_flag_old_unmatched(self):
        sub = _make_submission(submitted_date=date.today() - timedelta(days=config.MISSING_DAYS + 1))
        flags = compute_flags(sub, match=None)
        assert len(flags) == 1
        assert flags[0].flag == "MISSING"
        assert flags[0].severity == "red"

    def test_stale_pending_flag(self):
        sub = _make_submission()
        match = _make_match(status="Pending", received_date=date.today() - timedelta(days=config.STALE_PENDING_DAYS + 1))
        flags = compute_flags(sub, match=match)
        assert any(f.flag == "STALE_PENDING" for f in flags)

    def test_no_stale_if_no_received_date(self):
        sub = _make_submission()
        match = _make_match(status="Pending", received_date=None)
        flags = compute_flags(sub, match=match)
        assert not any(f.flag == "STALE_PENDING" for f in flags)

    def test_denied_flag(self):
        sub = _make_submission()
        match = _make_match(status="Denied")
        flags = compute_flags(sub, match=match)
        assert any(f.flag == "DENIED" and f.severity == "red" for f in flags)

    def test_underpaid_by_dollars(self):
        sub = _make_submission(expected_reimbursement=180_000)
        match = _make_match(status="Approved", plan_paid_val=150_000)  # $300 diff > $25 threshold
        flags = compute_flags(sub, match=match)
        assert any(f.flag == "UNDERPAID" for f in flags)

    def test_not_underpaid_small_diff(self):
        sub = _make_submission(expected_reimbursement=180_000)
        match = _make_match(status="Approved", plan_paid_val=179_000)  # $10 diff < $25 threshold
        flags = compute_flags(sub, match=match)
        assert not any(f.flag == "UNDERPAID" for f in flags)

    def test_approved_zero_paid_flag(self):
        sub = _make_submission()
        match = _make_match(status="Approved", plan_paid_val=0, your_cost=50_000)
        flags = compute_flags(sub, match=match)
        assert any(f.flag == "APPROVED_ZERO_PAID" and f.severity == "info" for f in flags)

    def test_no_approved_zero_if_your_cost_zero(self):
        sub = _make_submission()
        match = _make_match(status="Approved", plan_paid_val=0, your_cost=0)
        flags = compute_flags(sub, match=match)
        assert not any(f.flag == "APPROVED_ZERO_PAID" for f in flags)
