from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ProviderAlias
from app.schemas import ProviderAliasResponse

router = APIRouter()


@router.get("/providers/aliases", response_model=list[ProviderAliasResponse])
def list_aliases(db: Session = Depends(get_db)):
    return db.scalars(select(ProviderAlias)).all()


@router.delete("/providers/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: int, db: Session = Depends(get_db)):
    alias = db.get(ProviderAlias, alias_id)
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")
    db.delete(alias)
    db.commit()
