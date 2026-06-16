import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import credentials

_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "state.json"
_SCRIPT = Path(__file__).parent.parent.parent / "automation" / "fetch_all.py"
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


def get_status() -> dict:
    with _lock:
        return _read()


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
        state = _read()
        if state["status"] == "running":
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
