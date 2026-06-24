import json
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PlanConfig
from app.schemas import PlanConfigResponse, PlanConfigUpdate

router = APIRouter()

_CREDENTIALS_FILE = Path(__file__).parent.parent.parent.parent / "data" / "credentials.json"


class CredentialsSave(BaseModel):
    username: str
    password: str


@router.get("/settings/credentials")
def get_credentials():
    if _CREDENTIALS_FILE.exists():
        try:
            creds = json.loads(_CREDENTIALS_FILE.read_text())
            return {"username": creds.get("username", ""), "has_password": bool(creds.get("password"))}
        except Exception:
            pass
    return {"username": "", "has_password": False}


@router.post("/settings/credentials", status_code=204)
def save_credentials(body: CredentialsSave):
    _CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CREDENTIALS_FILE.write_text(json.dumps({"username": body.username, "password": body.password}))


def _get_or_create_plan_config(db: Session) -> PlanConfig:
    cfg = db.get(PlanConfig, 1)
    if cfg is None:
        cfg = PlanConfig(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


@router.get("/settings/plan-config", response_model=PlanConfigResponse)
def get_plan_config(db: Session = Depends(get_db)):
    cfg = _get_or_create_plan_config(db)
    return PlanConfigResponse(
        in_network_coinsurance_pct=cfg.in_network_coinsurance_pct,
        out_of_network_coinsurance_pct=cfg.out_of_network_coinsurance_pct,
    )


@router.put("/settings/plan-config", response_model=PlanConfigResponse)
def update_plan_config(body: PlanConfigUpdate, db: Session = Depends(get_db)):
    cfg = _get_or_create_plan_config(db)
    cfg.in_network_coinsurance_pct = body.in_network_coinsurance_pct
    cfg.out_of_network_coinsurance_pct = body.out_of_network_coinsurance_pct
    db.commit()
    db.refresh(cfg)
    return PlanConfigResponse(
        in_network_coinsurance_pct=cfg.in_network_coinsurance_pct,
        out_of_network_coinsurance_pct=cfg.out_of_network_coinsurance_pct,
    )
