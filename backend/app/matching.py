import re
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import select, exists

from app.models import Submission, AnthemClaim, Match, ProviderAlias


def normalize(s: str) -> str:
    """Lowercase, collapse whitespace, strip non-alphanumeric except spaces."""
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return s


def _provider_matches(
    sub_provider: str,
    claim_provider: str,
    alias_pairs: list[tuple[str, str]],
) -> bool:
    """True if providers match by exact name, prefix, or known alias."""
    n_sub = normalize(sub_provider)
    n_claim = normalize(claim_provider)

    if n_sub == n_claim:
        return True

    # If we have aliases, check them first
    if alias_pairs:
        # Collect all values mentioned in aliases
        all_alias_values = set()
        for canonical, anthem in alias_pairs:
            all_alias_values.add(canonical)
            all_alias_values.add(anthem)

        # If either provider is involved in any alias, only use alias matching
        if n_sub in all_alias_values or n_claim in all_alias_values:
            for canonical, anthem in alias_pairs:
                if canonical == n_sub and anthem == n_claim:
                    return True
            return False

    # Otherwise, allow prefix matching (for Anthem truncation and abbreviations)
    if n_sub.startswith(n_claim) or n_claim.startswith(n_sub):
        return True

    return False


@dataclass
class MatchResult:
    auto_matched: list[tuple[str, str]] = field(default_factory=list)
    suggestions: list[tuple[str, list[str]]] = field(default_factory=list)


def run_matching(db: Session) -> MatchResult:
    # Implemented in Task 6
    raise NotImplementedError
