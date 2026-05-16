import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AnthemClaim, BenefitsSnapshot
from app.matching import run_matching, MatchResult


def _parse_money(s: str) -> int:
    """Parse '$1,190.00' or '1190.00' or '' to integer cents."""
    s = s.strip().strip('"').lstrip('$').replace(',', '')
    if not s or s.lower() == 'not available':
        return 0
    return round(float(s) * 100)


def _parse_date(s: str) -> Optional[date]:
    """Parse 'YYYY-MM-DD' to date, or return None for empty/'Not Available'."""
    s = s.strip()
    if not s or s.lower() == 'not available':
        return None
    return date.fromisoformat(s)


def _parse_patient_name(s: str) -> str:
    """Parse 'Nolan O'leary (2019-02-14)' -> 'Nolan O'leary'."""
    s = s.strip()
    idx = s.rfind(' (')
    if idx != -1:
        return s[:idx]
    return s


def _normalize_status(s: str) -> str:
    """Normalize Anthem status to Pending/Approved/Denied."""
    normalized = s.strip().capitalize()
    if normalized not in ('Pending', 'Approved', 'Denied'):
        raise ValueError(f"Unknown claim status: {s!r}")
    return normalized


@dataclass
class IngestResult:
    new: int = 0
    updated: int = 0
    auto_matched: int = 0
    suggestions: int = 0


def ingest_claims_csv(db: Session, csv_bytes: bytes) -> IngestResult:
    text = csv_bytes.decode('utf-8-sig')  # utf-8-sig strips BOM if present
    reader = csv.DictReader(io.StringIO(text))

    now = datetime.now(timezone.utc)
    new_count = 0
    updated_count = 0

    for row in reader:
        claim_number = (row.get('Claim #') or row.get('Claim Number', '')).strip()
        existing = db.get(AnthemClaim, claim_number)

        fields = {
            'claim_type': (row.get('Claim Type') or row.get('Type', 'Medical')).strip(),
            'patient_name': _parse_patient_name(row['Patient']),
            'service_date': _parse_date(row['Service Date']),
            'received_date': _parse_date(row.get('Claim Received') or row.get('Received Date', '')),
            'processed_date': _parse_date(row.get('Processed Date', '')),
            'status': _normalize_status(row['Status']),
            'provider_name': (row.get('Provided By') or row.get('Provider', '')).strip(),
            'billed': _parse_money(row.get('Billed', '0')),
            'plan_discount': _parse_money(row.get('Plan Discount', '0')),
            'allowed': _parse_money(row.get('Allowed', '0')),
            'plan_paid': _parse_money(row.get('Plan Paid', '0')),
            'additional_savings': _parse_money(row.get('Additional Savings', '0')),
            'deductible': _parse_money(row.get('Deductible', '0')),
            'coinsurance': _parse_money(row.get('Coinsurance', '0')),
            'copay': _parse_money(row.get('Copay', '0')),
            'not_covered': _parse_money(row.get('Not Covered', '0')),
            'your_cost': _parse_money(row.get('Your Cost', '0')),
            'last_seen_at': now,
        }

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            updated_count += 1
        else:
            db.add(AnthemClaim(claim_number=claim_number, first_seen_at=now, **fields))
            new_count += 1

    db.commit()

    match_result = run_matching(db)
    return IngestResult(
        new=new_count,
        updated=updated_count,
        auto_matched=len(match_result.auto_matched),
        suggestions=len(match_result.suggestions),
    )


def ingest_benefits(db: Session, data: dict) -> None:
    now = datetime.now(timezone.utc)
    for network_key, network_data in data.items():
        db.add(BenefitsSnapshot(
            snapshot_date=now,
            network=network_key,
            deductible_limit=_parse_money(str(network_data['deductible_limit'])),
            deductible_spent=_parse_money(str(network_data['deductible_spent'])),
            oop_limit=_parse_money(str(network_data['oop_limit'])),
            oop_spent=_parse_money(str(network_data['oop_spent'])),
        ))
    db.commit()
