from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.static_serve import create_spa_router
from app.routes import (
    anthem_claims,
    automation,
    dashboard,
    ingest,
    matches,
    providers,
    settings,
    submissions,
    totals,
)

app = FastAPI(title="Claims Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(submissions.router, prefix="/api")
app.include_router(anthem_claims.router, prefix="/api")
app.include_router(matches.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(totals.router, prefix="/api")
app.include_router(automation.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(settings.router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.include_router(create_spa_router(_DIST))
