from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import config
from app.database import get_db
from app.models import AnthemClaim, BenefitsSnapshot, Match, Submission
from app.schemas import BenefitsSnapshotOut, CsvRollup, NetworkTotals, TotalsResponse

router = APIRouter()


def _get_latest_snapshots(db: Session) -> dict:
    """Return the most recent BenefitsSnapshot per network."""
    subq = (
        select(BenefitsSnapshot.network, func.max(BenefitsSnapshot.snapshot_date).label("max_date"))
        .group_by(BenefitsSnapshot.network)
        .subquery()
    )
    snaps = db.scalars(
        select(BenefitsSnapshot).join(
            subq,
            (BenefitsSnapshot.network == subq.c.network)
            & (BenefitsSnapshot.snapshot_date == subq.c.max_date),
        )
    ).all()
    return {s.network: s for s in snaps}


def _get_csv_rollup(db: Session) -> dict:
    """Sum deductible + coinsurance per network bucket for plan-year claims."""
    claims = db.scalars(
        select(AnthemClaim)
        .where(
            AnthemClaim.service_date >= config.PLAN_YEAR_START,
            AnthemClaim.service_date <= config.PLAN_YEAR_END,
        )
        .options(selectinload(AnthemClaim.match).selectinload(Match.submission))
    ).all()

    rollup: dict[str, dict[str, int]] = {
        "in_network": {"deductible": 0, "coinsurance": 0},
        "out_of_network": {"deductible": 0, "coinsurance": 0},
    }

    for claim in claims:
        if claim.match and claim.match.submission:
            treatment = claim.match.submission.network_treatment
            bucket = "in_network" if treatment == "in_network_exception" else "out_of_network"
        else:
            bucket = "in_network"
        rollup[bucket]["deductible"] += claim.deductible
        rollup[bucket]["coinsurance"] += claim.coinsurance

    return rollup


@router.get("/totals", response_model=TotalsResponse)
def get_totals(db: Session = Depends(get_db)):
    snaps = _get_latest_snapshots(db)
    rollup = _get_csv_rollup(db)
    result = {}

    for network in ("in_network", "out_of_network"):
        snap = snaps.get(network)
        ded_sum = rollup[network]["deductible"]
        coins_sum = rollup[network]["coinsurance"]
        total_sum = ded_sum + coins_sum

        ded_diff = (snap.deductible_spent - ded_sum) if snap else 0
        oop_diff = (snap.oop_spent - total_sum) if snap else 0
        has_drift = (
            abs(ded_diff) > config.TOTALS_DRIFT_THRESHOLD_CENTS
            or abs(oop_diff) > config.TOTALS_DRIFT_THRESHOLD_CENTS
        )

        result[network] = NetworkTotals(
            benefits=BenefitsSnapshotOut(
                deductible_limit=snap.deductible_limit,
                deductible_spent=snap.deductible_spent,
                oop_limit=snap.oop_limit,
                oop_spent=snap.oop_spent,
            ) if snap else None,
            csv_rollup=CsvRollup(
                deductible_sum=ded_sum,
                coinsurance_sum=coins_sum,
                total_sum=total_sum,
            ),
            deductible_diff=ded_diff,
            oop_diff=oop_diff,
            has_drift=has_drift,
        )

    return TotalsResponse(in_network=result["in_network"], out_of_network=result["out_of_network"])
