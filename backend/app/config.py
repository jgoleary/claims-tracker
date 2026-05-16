from datetime import date

# Alert thresholds
MISSING_DAYS = 30
STALE_PENDING_DAYS = 45
UNDERPAID_MIN_CENTS = 2_500   # $25.00
UNDERPAID_PCT = 0.10          # 10%
TOTALS_DRIFT_THRESHOLD_CENTS = 5_000  # $50.00


def plan_year_dates(year: int) -> tuple[date, date]:
    """Return (Jan 1, Dec 31) for the given calendar year."""
    return date(year, 1, 1), date(year, 12, 31)
