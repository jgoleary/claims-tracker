import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import credentials
from app.storage import get_storage

_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "state.json"
_ESC_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "escalation_state.json"
_FILING_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "claim_filing_state.json"
_SCRIPT = Path(__file__).parent.parent.parent / "automation" / "fetch_all.py"
_ESC_SCRIPT = Path(__file__).parent.parent.parent / "automation" / "ih_escalate.py"
_FILING_SCRIPT = Path(__file__).parent.parent.parent / "automation" / "submit_claim.py"
_lock = threading.Lock()

# Subprocess timeouts (also the basis for stale-run detection).
_REFRESH_TIMEOUT_S = 300
_ESC_TIMEOUT_S = 600  # 10 min — covers interactive login + form review
# 30 min: MFA login (≤120s) + questionnaire readiness (≤240s) + the wizard
# (~60s) + Anthem's file processing (≤180s) + the 15-min handoff hold, + margin.
_FILING_TIMEOUT_S = 1800
# A "running" state older than its timeout + this margin is treated as stale: the
# worker must have died (dev reload, crash, sleep) without writing a terminal
# status, so it no longer blocks new runs.
_STALE_MARGIN_S = 120


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


def _read_claim_filing() -> dict:
    if _FILING_STATE_FILE.exists():
        try:
            return json.loads(_FILING_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"status": "idle", "submission_id": None, "last_run_at": None, "summary": None}


def _write_claim_filing(state: dict) -> None:
    _FILING_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILING_STATE_FILE.write_text(json.dumps(state))


def _is_running(state: dict, timeout_s: int) -> bool:
    """True only if the state is 'running' AND fresh. A run older than its
    subprocess timeout (plus margin) means the worker died without clearing the
    flag, so it's treated as not running — this auto-recovers stuck state."""
    if state.get("status") != "running":
        return False
    started = state.get("started_at")
    if not started:
        return False  # legacy/orphaned 'running' with no timestamp → auto-clear
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()
    except (ValueError, TypeError):
        return False
    return age < timeout_s + _STALE_MARGIN_S


def _any_running() -> bool:
    """True if any Playwright job — refresh, escalation or claim filing — is
    genuinely in progress. They share one browser profile and run headfully, so
    only one at a time; every job checks this same guard."""
    return (
        _is_running(_read(), _REFRESH_TIMEOUT_S)
        or _is_running(_read_escalation(), _ESC_TIMEOUT_S)
        or _is_running(_read_claim_filing(), _FILING_TIMEOUT_S)
    )


def _normalized(state: dict, timeout_s: int) -> dict:
    """Report a stale 'running' state as 'idle' so the UI recovers too."""
    if state.get("status") == "running" and not _is_running(state, timeout_s):
        return {**state, "status": "idle"}
    return state


def get_status() -> dict:
    with _lock:
        return _normalized(_read(), _REFRESH_TIMEOUT_S)


def get_escalation_status() -> dict:
    with _lock:
        return _normalized(_read_escalation(), _ESC_TIMEOUT_S)


def get_claim_filing_status() -> dict:
    with _lock:
        return _normalized(_read_claim_filing(), _FILING_TIMEOUT_S)


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


def _run_subprocess(script: Path, env_extra: dict, timeout_s: int) -> tuple[str, dict]:
    """Run an automation script and normalize the outcome to (status, summary).

    Shared by every job type. Deliberately calls subprocess.run through the
    module global so tests can monkeypatch app.automation.subprocess.run.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(script.parent.parent),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, **env_extra},
        )
        return (
            "complete" if result.returncode == 0 else "failed",
            {
                "returncode": result.returncode,
                "stdout": result.stdout[-2_000:],
                "stderr": result.stderr[-500:],
            },
        )
    except subprocess.TimeoutExpired:
        return "failed", {"error": f"timed out after {timeout_s}s"}
    except Exception as e:
        return "failed", {"error": str(e)}


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
        _write({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_run_at": None,
            "summary": None,
        })

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

        status, summary = _run_subprocess(
            _SCRIPT,
            {"ANTHEM_USERNAME": creds[0], "ANTHEM_PASSWORD": creds[1]},
            _REFRESH_TIMEOUT_S,
        )

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


def _materialize_pdf(pdf_key: str | None) -> str:
    """Write the submission's stored PDF to a temp file and return its path, or ""
    if there's no PDF / it can't be read. The caller passes the path to
    _cleanup_pdf when done. Going through storage.get keeps this working for
    non-local Storage backends.

    The file keeps its original basename inside a temp *directory* — whoever
    receives the upload (an Anthem adjudicator, say) sees "claim.pdf" rather
    than "tmp8f3a91.pdf".
    """
    if not pdf_key:
        return ""
    try:
        data = get_storage().get(pdf_key)
    except Exception:
        return ""
    name = os.path.basename(pdf_key) or "claim.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _cleanup_pdf(path: str) -> None:
    """Remove a _materialize_pdf temp file and the directory holding it."""
    if not path:
        return
    try:
        if os.path.exists(path):
            os.unlink(path)
        os.rmdir(os.path.dirname(path))
    except OSError:
        pass


def run_escalation(
    submission_id: str,
    member_name: str,
    provider_name: str,
    service_date: str,
    message: str,
    pdf_key: str | None = None,
) -> bool:
    """Spawn ih_escalate.py in a background thread. Returns False if a refresh or
    escalation is already running (single browser at a time)."""
    with _lock:
        if _any_running():
            return False
        _write_escalation({
            "status": "running",
            "submission_id": submission_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_run_at": None,
            "summary": None,
        })

    def _worker():
        pdf_path = _materialize_pdf(pdf_key)
        try:
            # Long timeout: the headful window stays open while the user logs in
            # (if the session expired) and reviews/submits the filled form.
            status, summary = _run_subprocess(
                _ESC_SCRIPT,
                {
                    "IH_SUBMISSION_ID": submission_id,
                    "IH_MEMBER": member_name,
                    "IH_PROVIDER": provider_name,
                    "IH_SERVICE_DATE": service_date,
                    "IH_MESSAGE": message,
                    "IH_PDF_PATH": pdf_path,
                },
                _ESC_TIMEOUT_S,
            )
        finally:
            _cleanup_pdf(pdf_path)

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


def _classify_claim_filing_failure(summary: dict) -> str:
    """Turn the script's "stage: msg" output into an actionable notification."""
    text = (summary.get("stdout", "") + summary.get("stderr", "")).lower()
    if "patient:" in text or "could not pick the patient" in text:
        return ("Couldn't pick the patient on Anthem — choose it in the open browser "
                "window and finish there.")
    if "auth" in text and ("timeout" in text or "timed out" in text):
        return "Anthem filing needs sign-in — complete it in the browser window, then retry."
    if "rejected the uploaded pdf" in text:
        return "Anthem rejected the uploaded PDF — check the file and retry."
    return "Anthem claim filing failed — check the Submissions page for details."


def run_claim_filing(submission_id: str, member_name: str, pdf_key: str) -> bool:
    """Spawn submit_claim.py in a background thread. Returns False if any
    Playwright job is already running (single browser at a time).

    Deliberately has no post-success hook: the script only drives Anthem's
    wizard as far as the upload step, so whether the claim was actually filed is
    unknowable here. submitted_date stays the user's to confirm.
    """
    with _lock:
        if _any_running():
            return False
        _write_claim_filing({
            "status": "running",
            "submission_id": submission_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_run_at": None,
            "summary": None,
        })

    def _worker():
        pdf_path = _materialize_pdf(pdf_key)
        try:
            # Long timeout: the headful window stays open for sign-in and for the
            # 15-minute handoff while the user completes the remaining steps.
            status, summary = _run_subprocess(
                _FILING_SCRIPT,
                {
                    "CLAIM_SUBMISSION_ID": submission_id,
                    "CLAIM_MEMBER": member_name,
                    "CLAIM_PDF_PATH": pdf_path,
                },
                _FILING_TIMEOUT_S,
            )
        finally:
            _cleanup_pdf(pdf_path)

        with _lock:
            _write_claim_filing({
                "status": status,
                "submission_id": submission_id,
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
            })

        if status == "failed":
            notify("Claims Tracker", _classify_claim_filing_failure(summary))

    threading.Thread(target=_worker, daemon=True).start()
    return True
