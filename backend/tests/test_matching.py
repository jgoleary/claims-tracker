import pytest
from sqlalchemy.orm import Session
from app.models import Match, ProviderAlias
from app.matching import normalize, _provider_matches, run_matching
from datetime import date


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

    def test_prefix_match_with_unrelated_aliases_present(self):
        # Aliases exist but don't involve these providers — prefix match should still work
        aliases = [("citrus speech", "citrus speech and language")]
        assert _provider_matches("California Pacific", "California Pacific Medical Center", aliases)


class TestRunMatching:
    def test_auto_match_exact_provider(self, db: Session, make_submission, make_claim):
        sub = make_submission()
        claim = make_claim()
        result = run_matching(db)
        assert len(result.auto_matched) == 1
        assert result.auto_matched[0] == (sub.id, claim.claim_number)
        assert db.get(Match, sub.id) is not None

    def test_auto_match_prefix_provider(self, db: Session, make_submission, make_claim):
        sub = make_submission(provider_name="Joyful Behavior Therapy LLC")
        claim = make_claim(provider_name="Joyful Behavior Therapy L")
        result = run_matching(db)
        assert len(result.auto_matched) == 1

    def test_auto_match_via_alias(self, db: Session, make_submission, make_claim):
        alias = ProviderAlias(
            canonical_name="citrus speech",
            anthem_name="citrus speech and language",
        )
        db.add(alias)
        db.commit()
        sub = make_submission(provider_name="Citrus Speech")
        claim = make_claim(provider_name="Citrus Speech and Language")
        result = run_matching(db)
        assert len(result.auto_matched) == 1

    def test_no_match_different_date(self, db: Session, make_submission, make_claim):
        make_submission(service_date=date(2025, 11, 4))
        make_claim(service_date=date(2025, 10, 1))
        result = run_matching(db)
        assert result.auto_matched == []
        assert result.suggestions == []

    def test_no_match_different_member(self, db: Session, make_submission, make_claim):
        make_submission(member_name="James OLeary")
        make_claim(patient_name="Nolan OLeary")
        result = run_matching(db)
        assert result.auto_matched == []
        assert result.suggestions == []

    def test_tier1_conflict_becomes_suggestion(self, db: Session, make_submission, make_claim):
        sub = make_submission()
        claim1 = make_claim(claim_number="CLM-001")
        claim2 = make_claim(claim_number="CLM-002")
        result = run_matching(db)
        assert result.auto_matched == []
        assert len(result.suggestions) == 1
        assert set(result.suggestions[0][1]) == {"CLM-001", "CLM-002"}

    def test_tier2_suggestion_provider_mismatch(self, db: Session, make_submission, make_claim):
        sub = make_submission(provider_name="Dr. Smith Psychiatry")
        claim = make_claim(provider_name="Smith John MD")
        result = run_matching(db)
        assert result.auto_matched == []
        assert len(result.suggestions) == 1
        assert result.suggestions[0][0] == sub.id

    def test_already_matched_submission_skipped(self, db: Session, make_submission, make_claim):
        sub = make_submission()
        claim = make_claim()
        db.add(Match(submission_id=sub.id, anthem_claim_number=claim.claim_number, match_type="manual"))
        db.commit()
        result = run_matching(db)
        assert result.auto_matched == []

    def test_already_matched_claim_skipped(self, db: Session, make_submission, make_claim):
        sub1 = make_submission(provider_name="Provider A")
        sub2 = make_submission(provider_name="Provider A")
        claim = make_claim(provider_name="Provider A")
        db.add(Match(submission_id=sub1.id, anthem_claim_number=claim.claim_number, match_type="manual"))
        db.commit()
        result = run_matching(db)
        # claim is already matched, sub2 should get no match
        assert result.auto_matched == []
