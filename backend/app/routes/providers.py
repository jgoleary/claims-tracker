from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.matching import normalize
from app.models import ProviderAlias, Submission
from app.schemas import ProviderAliasResponse

router = APIRouter()


@router.get("/providers/aliases", response_model=list[ProviderAliasResponse])
def list_aliases(db: Session = Depends(get_db)):
    return db.scalars(select(ProviderAlias)).all()


@router.get("/providers/network-defaults")
def provider_network_defaults(db: Session = Depends(get_db)) -> dict[str, str]:
    """Map of normalized provider name -> most recently used network_treatment.

    The network treatment is a near-constant property of a provider, so the Add
    Submission form uses this to default the field to the provider's last value.
    """
    rows = db.scalars(select(Submission).order_by(Submission.created_at.desc())).all()
    out: dict[str, str] = {}
    for s in rows:
        key = normalize(s.provider_name)
        if key and key not in out:  # first hit wins = most recent
            out[key] = s.network_treatment
    return out


@router.delete("/providers/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: int, db: Session = Depends(get_db)):
    alias = db.get(ProviderAlias, alias_id)
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")
    db.delete(alias)
    db.commit()
