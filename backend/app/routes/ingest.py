from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingest import ingest_benefits, ingest_claims_csv
from app.schemas import BenefitsIngest, IngestSummary

router = APIRouter()


@router.post("/ingest/claims-csv", response_model=IngestSummary)
async def upload_claims_csv(file: UploadFile, db: Session = Depends(get_db)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=422, detail="File must be a .csv")
    try:
        data = await file.read()
        result = ingest_claims_csv(db, data)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"CSV parse error: {e}")
    return IngestSummary(
        new=result.new,
        updated=result.updated,
        auto_matched=result.auto_matched,
        suggestions=result.suggestions,
    )


@router.post("/ingest/benefits", status_code=204)
def ingest_benefits_route(body: BenefitsIngest, db: Session = Depends(get_db)):
    data = {
        "in_network": body.in_network.model_dump(),
        "out_of_network": body.out_of_network.model_dump(),
    }
    ingest_benefits(db, data)
