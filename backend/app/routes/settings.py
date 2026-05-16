import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

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
