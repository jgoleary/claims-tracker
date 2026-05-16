import pytest
from app.ingest import _parse_money, _parse_date, _parse_patient_name, _normalize_status
from datetime import date


class TestParseMoney:
    def test_dollar_sign_and_commas(self):
        assert _parse_money("$1,190.00") == 119_000

    def test_plain_number(self):
        assert _parse_money("350.00") == 35_000

    def test_zero(self):
        assert _parse_money("$0.00") == 0

    def test_empty_string(self):
        assert _parse_money("") == 0

    def test_not_available(self):
        assert _parse_money("Not Available") == 0

    def test_quoted_value(self):
        assert _parse_money('"$2,400.00"') == 240_000


class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2025-11-04") == date(2025, 11, 4)

    def test_not_available(self):
        assert _parse_date("Not Available") is None

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_strips_whitespace(self):
        assert _parse_date("  2025-11-04  ") == date(2025, 11, 4)


class TestParsePatientName:
    def test_strips_dob(self):
        assert _parse_patient_name("Nolan O'leary (2019-02-14)") == "Nolan O'leary"

    def test_no_dob(self):
        assert _parse_patient_name("James OLeary") == "James OLeary"

    def test_strips_whitespace(self):
        assert _parse_patient_name("  James OLeary  ") == "James OLeary"


class TestNormalizeStatus:
    def test_pending(self):
        assert _normalize_status("Pending") == "Pending"

    def test_lowercase_approved(self):
        assert _normalize_status("approved") == "Approved"

    def test_uppercase_denied(self):
        assert _normalize_status("DENIED") == "Denied"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown claim status"):
            _normalize_status("Cancelled")
