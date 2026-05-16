import pytest
from app.matching import normalize, _provider_matches


class TestNormalize:
    def test_lowercases(self):
        assert normalize("JOYFUL BEHAVIOR") == "joyful behavior"

    def test_strips_leading_trailing_whitespace(self):
        assert normalize("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self):
        assert normalize("joyful  behavior   therapy") == "joyful behavior therapy"

    def test_strips_punctuation(self):
        assert normalize("St. Mary's") == "st marys"

    def test_strips_special_chars(self):
        assert normalize("O'Leary, James") == "oleary james"

    def test_keeps_numbers(self):
        assert normalize("Provider 123") == "provider 123"

    def test_empty_string(self):
        assert normalize("") == ""


class TestProviderMatches:
    def test_exact_match(self):
        assert _provider_matches("Joyful Behavior Therapy", "Joyful Behavior Therapy", [])

    def test_exact_match_case_insensitive(self):
        assert _provider_matches("JOYFUL BEHAVIOR", "joyful behavior", [])

    def test_prefix_match_claim_truncated(self):
        # Anthem truncates at ~25 chars
        assert _provider_matches("Joyful Behavior Therapy LLC", "Joyful Behavior Therapy L", [])

    def test_prefix_match_submission_shorter(self):
        assert _provider_matches("California Pacific", "California Pacific Medical Center", [])

    def test_alias_match(self):
        aliases = [("citrus speech", "citrus speech and language")]
        assert _provider_matches("Citrus Speech", "Citrus Speech and Language", aliases)

    def test_no_match(self):
        assert not _provider_matches("Dr. Smith", "Joyful Behavior Therapy", [])

    def test_alias_wrong_direction_no_match(self):
        # Aliases are directional: canonical -> anthem
        aliases = [("citrus speech", "citrus speech and language")]
        assert not _provider_matches("Citrus Speech and Language", "Citrus Speech", aliases)
