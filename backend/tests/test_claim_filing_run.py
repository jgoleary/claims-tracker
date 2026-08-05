"""Runner tests for the Anthem claim-filing job.

Same shape as test_escalation_run.py: the worker thread is made synchronous and
subprocess.run is stubbed, so nothing spawns a process or opens a browser.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app import automation as _auto
from app.models import Submission


class _SyncThread:
    """Runs the worker synchronously so tests can assert on its effects."""
    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        self._target()


def _running(age_seconds: int = 0, **extra) -> dict:
    started = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return {"status": "running", "started_at": started, **extra}


def _idle(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_claim_filing", lambda: {"status": "idle"})


def _run(monkeypatch, **kw):
    """Start a filing run with state writes captured."""
    writes: list[dict] = []
    monkeypatch.setattr(_auto, "_write_claim_filing", lambda s: writes.append(s))
    monkeypatch.setattr(_auto.threading, "Thread", _SyncThread)
    monkeypatch.setattr(_auto, "notify", lambda *a: None)
    monkeypatch.setattr(_auto.subprocess, "run",
                        lambda *a, **k: MagicMock(returncode=0, stdout="ok", stderr=""))
    for name, value in kw.items():
        monkeypatch.setattr(_auto.subprocess if name == "run" else _auto, name, value)
    return writes


# ── single-flight, in both directions ────────────────────────────────────────

def test_refuses_when_refresh_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: _running())
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_claim_filing", lambda: {"status": "idle"})
    assert _auto.run_claim_filing("s1", "Nolan", "s1/claim.pdf") is False


def test_refuses_when_escalation_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: _running())
    monkeypatch.setattr(_auto, "_read_claim_filing", lambda: {"status": "idle"})
    assert _auto.run_claim_filing("s1", "Nolan", "s1/claim.pdf") is False


def test_refuses_when_another_filing_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_claim_filing", lambda: _running())
    assert _auto.run_claim_filing("s1", "Nolan", "s1/claim.pdf") is False


def test_refresh_refuses_when_filing_running(monkeypatch):
    """Proves the new state file was actually wired into _any_running()."""
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_claim_filing", lambda: _running())
    assert _auto.run_automation("u", "p") is False


def test_escalation_refuses_when_filing_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_claim_filing", lambda: _running())
    assert _auto.run_escalation("s1", "m", "p", "2026-01-01", "msg") is False


# ── stale-run auto-recovery ──────────────────────────────────────────────────

def test_starts_when_prior_filing_is_stale(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_claim_filing", lambda: _running(age_seconds=5_000))
    writes = _run(monkeypatch)
    assert _auto.run_claim_filing("s1", "Nolan", "s1/claim.pdf") is True
    assert writes[0]["status"] == "running"
    assert writes[0].get("started_at")


def test_status_normalizes_stale_to_idle(monkeypatch):
    monkeypatch.setattr(_auto, "_read_claim_filing",
                        lambda: _running(age_seconds=5_000, submission_id="x"))
    assert _auto.get_claim_filing_status()["status"] == "idle"


# ── worker behaviour ─────────────────────────────────────────────────────────

def test_success_writes_complete(monkeypatch):
    _idle(monkeypatch)
    writes = _run(monkeypatch)
    assert _auto.run_claim_filing("sub-1", "Nolan", "sub-1/claim.pdf") is True
    assert writes[-1]["status"] == "complete"
    assert writes[-1]["submission_id"] == "sub-1"


def test_failure_writes_failed_and_notifies(monkeypatch):
    _idle(monkeypatch)
    notes: list[str] = []
    writes = _run(monkeypatch)
    monkeypatch.setattr(_auto, "notify", lambda title, msg: notes.append(msg))
    monkeypatch.setattr(
        _auto.subprocess, "run",
        lambda *a, **k: MagicMock(
            returncode=1,
            stdout="[patient] ERROR: Could not pick the patient for member 'Nolan'",
            stderr="",
        ))

    assert _auto.run_claim_filing("sub-1", "Nolan", "sub-1/claim.pdf") is True
    assert writes[-1]["status"] == "failed"
    assert "choose it in the open browser" in notes[0]


def test_env_vars_passed_to_script(monkeypatch):
    _idle(monkeypatch)
    _run(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(_auto.subprocess, "run",
                        lambda *a, **k: captured.update(env=k["env"], argv=a[0]) or
                        MagicMock(returncode=0, stdout="", stderr=""))

    class FakeStorage:
        def get(self, key):
            return b"%PDF-1.4 fake"

    monkeypatch.setattr(_auto, "get_storage", lambda: FakeStorage())

    assert _auto.run_claim_filing("sub-1", "Nolan", "sub-1/claim.pdf") is True
    assert captured["env"]["CLAIM_SUBMISSION_ID"] == "sub-1"
    assert captured["env"]["CLAIM_MEMBER"] == "Nolan"
    assert captured["env"]["CLAIM_PDF_PATH"].endswith("claim.pdf")
    assert str(_auto._FILING_SCRIPT) in captured["argv"]


def test_pdf_materialized_with_original_name_and_cleaned_up(monkeypatch):
    _idle(monkeypatch)
    _run(monkeypatch)

    class FakeStorage:
        def get(self, key):
            assert key == "sub-1/claim.pdf"
            return b"%PDF-1.4 fake"

    monkeypatch.setattr(_auto, "get_storage", lambda: FakeStorage())

    captured: dict = {}

    def fake_run(*a, **k):
        path = k["env"]["CLAIM_PDF_PATH"]
        captured["path"] = path
        captured["exists_during"] = os.path.exists(path)
        captured["content"] = open(path, "rb").read()
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_auto.subprocess, "run", fake_run)

    assert _auto.run_claim_filing("sub-1", "Nolan", "sub-1/claim.pdf") is True
    assert captured["exists_during"] is True
    assert captured["content"] == b"%PDF-1.4 fake"
    # Uploaded under a human-readable name, not tmpXXXX.pdf.
    assert os.path.basename(captured["path"]) == "claim.pdf"
    # Temp file and its directory are cleaned up after the subprocess returns.
    assert not os.path.exists(captured["path"])
    assert not os.path.exists(os.path.dirname(captured["path"]))


def test_success_does_not_stamp_submitted_date(monkeypatch, db, make_submission):
    """The wizard is only driven to the upload step, so the job must never
    conclude the claim was filed — the user confirms that themselves."""
    sub = make_submission(submitted_date=None)
    _idle(monkeypatch)
    _run(monkeypatch)

    assert _auto.run_claim_filing(sub.id, sub.member_name, "k/claim.pdf") is True

    db.expire_all()
    refreshed = db.get(Submission, sub.id)
    assert refreshed.submitted_date is None
