from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts import compute_flags
from app.config import plan_year_dates
from app.database import get_db
from app.models import Submission
from app.routes.submissions import _load_options
from app.schemas import DashboardAlert, DashboardCounts, DashboardResponse

router = APIRouter()


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(year: Optional[int] = None, db: Session = Depends(get_db)):
    if year is None:
        year = date.today().year
    start, end = plan_year_dates(year)
    submissions = db.scalars(
        select(Submission)
        .where(Submission.service_date >= start, Submission.service_date <= end)
        .options(_load_options())
    ).all()

    counts = DashboardCounts()
    alerts: list[DashboardAlert] = []

    for sub in submissions:
        flags = compute_flags(sub, sub.match)
        for flag in flags:
            alerts.append(DashboardAlert(
                submission_id=sub.id,
                flag=flag.flag,
                severity=flag.severity,
                details=flag.details,
            ))
            if flag.flag == "MISSING":
                counts.missing += 1
            elif flag.flag == "STALE_PENDING":
                counts.stale_pending += 1
            elif flag.flag == "DENIED":
                counts.denied += 1
            elif flag.flag == "UNDERPAID":
                counts.underpaid += 1

    # Sort: red first, then yellow, then info
    severity_order = {"red": 0, "yellow": 1, "info": 2}
    alerts.sort(key=lambda a: severity_order.get(a.severity, 99))

    return DashboardResponse(counts=counts, alerts=alerts)
