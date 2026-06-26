import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import credentials

_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "state.json"
_ESC_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "escalation_state.json"
_SCRIPT = Path(__file__).parent.parent.parent / "automation" / "fetch_all.py"
_ESC_SCRIPT = Path(__file__).parent.parent.parent / "automation" / "ih_escalate.py"
_lock = threading.Lock()


def _read() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"status": "idle", "last_run_at": None, "summary": None}


def _write(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state))


def _read_escalation() -> dict:
    if _ESC_STATE_FILE.exists():
        try:
            return json.loads(_ESC_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"status": "idle", "submission_id": None, "last_run_at": None, "summary": None}


def _write_escalation(state: dict) -> None:
    _ESC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ESC_STATE_FILE.write_text(json.dumps(state))


def _any_running() -> bool:
    """True if either the Anthem refresh or an escalation is in progress. Only one
    Playwright/browser job runs at a time, so both jobs share this guard."""
    return _read()["status"] == "running" or _read_escalation()["status"] == "running"


def get_status() -> dict:
    with _lock:
        return _read()


def get_escalation_status() -> dict:
    with _lock:
        return _read_escalation()


def notify(title: str, message: str) -> None:
    """Best-effort macOS notification; no-op if osascript is unavailable."""
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification {message!r} with title {title!r}'],
            check=False,
            timeout=10,
        )
    except Exception:
        pass


def _resolve_credentials(username: str, password: str) -> tuple[str, str] | None:
    if username and password:
        return username, password
    return credentials.get_credentials()


def _classify_failure(summary: dict) -> str:
    text = (summary.get("stdout", "") + summary.get("stderr", "")).lower()
    if "auth" in text and "timeout" in text:
        return "Anthem refresh needs MFA — open the Refresh page and run it manually."
    return "Anthem refresh failed — check the Refresh page for details."


def run_automation(username: str = "", password: str = "") -> bool:
    """Spawn fetch_all.py in a background thread. Returns False if already running."""
    with _lock:
        if _any_running():
            return False
        _write({"status": "running", "last_run_at": None, "summary": None})

    def _worker():
        creds = _resolve_credentials(username, password)
        if creds is None:
            with _lock:
                _write({
                    "status": "failed",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "summary": {"error": "no stored credentials"},
                })
            notify(
                "Claims Tracker",
                "No stored Anthem credentials — run deploy/store_credentials.py.",
            )
            return

        env = {**os.environ, "ANTHEM_USERNAME": creds[0], "ANTHEM_PASSWORD": creds[1]}
        try:
            result = subprocess.run(
                [sys.executable, str(_SCRIPT)],
                cwd=str(_SCRIPT.parent.parent),
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
            summary = {
                "returncode": result.returncode,
                "stdout": result.stdout[-2_000:],
                "stderr": result.stderr[-500:],
            }
            status = "complete" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            summary = {"error": "timed out after 300s"}
            status = "failed"
        except Exception as e:
            summary = {"error": str(e)}
            status = "failed"

        with _lock:
            _write({
                "status": status,
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
            })

        if status == "failed":
            notify("Claims Tracker", _classify_failure(summary))

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _mark_escalated(submission_id: str, session_factory=None) -> None:
    """Stamp escalated_at on the submission after a successful escalation run."""
    from app.database import SessionLocal
    from app.models import Submission

    db = (session_factory or SessionLocal)()
    try:
        sub = db.get(Submission, submission_id)
        if sub is not None:
            sub.escalated_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def run_escalation(
    submission_id: str,
    member_name: str,
    provider_name: str,
    service_date: str,
    message: str,
) -> bool:
    """Spawn ih_escalate.py in a background thread. Returns False if a refresh or
    escalation is already running (single browser at a time)."""
    with _lock:
        if _any_running():
            return False
        _write_escalation({
            "status": "running",
            "submission_id": submission_id,
            "last_run_at": None,
            "summary": None,
        })

    def _worker():
        env = {
            **os.environ,
            "IH_SUBMISSION_ID": submission_id,
            "IH_MEMBER": member_name,
            "IH_PROVIDER": provider_name,
            "IH_SERVICE_DATE": service_date,
            "IH_MESSAGE": message,
        }
        try:
            # Long timeout: the headful window stays open while the user logs in
            # (if the session expired) and reviews/submits the filled form.
            result = subprocess.run(
                [sys.executable, str(_ESC_SCRIPT)],
                cwd=str(_ESC_SCRIPT.parent.parent),
                capture_output=True,
                text=True,
                timeout=1_800,
                env=env,
            )
            summary = {
                "returncode": result.returncode,
                "stdout": result.stdout[-2_000:],
                "stderr": result.stderr[-500:],
            }
            status = "complete" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            summary = {"error": "timed out after 1800s"}
            status = "failed"
        except Exception as e:
            summary = {"error": str(e)}
            status = "failed"

        if status == "complete":
            _mark_escalated(submission_id)

        with _lock:
            _write_escalation({
                "status": status,
                "submission_id": submission_id,
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
            })

        if status == "failed":
            notify("Claims Tracker", _classify_escalation_failure(summary))

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _classify_escalation_failure(summary: dict) -> str:
    text = (summary.get("stdout", "") + summary.get("stderr", "")).lower()
    if "auth" in text and "timeout" in text:
        return "Included Health escalation needs login — open the browser and sign in, then retry."
    return "Included Health escalation failed — check the Submissions page for details."
