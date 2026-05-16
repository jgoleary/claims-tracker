from fastapi import APIRouter

from app import automation as _automation
from app.schemas import AutomationStatus

router = APIRouter()


@router.post("/automation/run", status_code=202)
def run_automation():
    started = _automation.run_automation()
    if not started:
        return {"detail": "Automation already running"}
    return {"detail": "Automation started"}


@router.get("/automation/status", response_model=AutomationStatus)
def get_status():
    state = _automation.get_status()
    return AutomationStatus(
        status=state["status"],
        last_run_at=state.get("last_run_at"),
        summary=state.get("summary"),
    )
