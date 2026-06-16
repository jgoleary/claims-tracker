"""Serve the built Vite SPA (frontend/dist) from FastAPI for production."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def create_spa_router(dist: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    return router
