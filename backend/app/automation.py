import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

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


def run_automation(username: str = "", password: str = "") -> bool:
    """Spawn fetch_all.py in a background thread. Returns False if already running."""
    with _lock:
        state = _read()
        if state["status"] == "running":
            return False
        _write({"status": "running", "last_run_at": None, "summary": None})

    def _worker():
        env = {**os.environ}
        if username:
            env["ANTHEM_USERNAME"] = username
        if password:
            env["ANTHEM_PASSWORD"] = password
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

    threading.Thread(target=_worker, daemon=True).start()
    return True
