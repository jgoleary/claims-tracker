from datetime import date

# Alert thresholds
MISSING_DAYS = 30
STALE_PENDING_DAYS = 45
UNDERPAID_MIN_CENTS = 2_500   # $25.00
UNDERPAID_PCT = 0.10          # 10%
TOTALS_DRIFT_THRESHOLD_CENTS = 5_000  # $50.00

# Plan year (update each January)
PLAN_YEAR_START = date(2025, 1, 1)
PLAN_YEAR_END = date(2025, 12, 31)
