import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy.orm import sessionmaker

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
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle", "submission_id": None})


# ── single-flight ────────────────────────────────────────────────────────────

def test_any_running_true_when_refresh_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: _running())
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    assert _auto._any_running() is True


def test_run_escalation_refuses_when_refresh_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: _running())
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    assert _auto.run_escalation("s1", "m", "p", "2025-01-01", "msg") is False


def test_run_escalation_refuses_when_escalation_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: _running())
    assert _auto.run_escalation("s1", "m", "p", "2025-01-01", "msg") is False


def test_run_automation_refuses_when_escalation_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: _running())
    assert _auto.run_automation("u", "p") is False


# ── stale-run auto-recovery ──────────────────────────────────────────────────

def test_is_running_recent_true():
    assert _auto._is_running(_running(age_seconds=0), 600) is True


def test_is_running_stale_false():
    assert _auto._is_running(_running(age_seconds=5_000), 600) is False


def test_is_running_missing_started_at_false():
    # Legacy/orphaned state with no timestamp auto-clears.
    assert _auto._is_running({"status": "running"}, 600) is False


def test_any_running_false_when_escalation_stale(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: _running(age_seconds=5_000))
    assert _auto._any_running() is False


def test_get_escalation_status_normalizes_stale_to_idle(monkeypatch):
    monkeypatch.setattr(_auto, "_read_escalation", lambda: _running(age_seconds=5_000, submission_id="x"))
    assert _auto.get_escalation_status()["status"] == "idle"


def test_run_escalation_starts_when_prior_run_is_stale(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: _running(age_seconds=5_000))
    writes: list[dict] = []
    monkeypatch.setattr(_auto, "_write_escalation", lambda s: writes.append(s))
    monkeypatch.setattr(_auto, "_mark_escalated", lambda sid: None)
    monkeypatch.setattr(_auto.subprocess, "run",
                        lambda *a, **k: MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(_auto.threading, "Thread", _SyncThread)

    assert _auto.run_escalation("s1", "m", "p", "2025-11-04", "msg") is True
    assert writes[0]["status"] == "running"
    assert writes[0].get("started_at")  # new runs stamp a start time


# ── worker behaviour ─────────────────────────────────────────────────────────

def test_run_escalation_success_marks_escalated(monkeypatch):
    _idle(monkeypatch)
    writes: list[dict] = []
    marked: list[str] = []
    monkeypatch.setattr(_auto, "_write_escalation", lambda s: writes.append(s))
    monkeypatch.setattr(_auto, "_mark_escalated", lambda sid: marked.append(sid))
    monkeypatch.setattr(_auto.subprocess, "run",
                        lambda *a, **k: MagicMock(returncode=0, stdout="ok", stderr=""))
    monkeypatch.setattr(_auto.threading, "Thread", _SyncThread)

    assert _auto.run_escalation("sub-1", "Nolan O'Leary", "Dr X", "2025-11-04", "hi") is True
    assert marked == ["sub-1"]
    assert writes[-1]["status"] == "complete"
    assert writes[-1]["submission_id"] == "sub-1"


def test_run_escalation_failure_does_not_mark(monkeypatch):
    _idle(monkeypatch)
    writes: list[dict] = []
    marked: list[str] = []
    monkeypatch.setattr(_auto, "_write_escalation", lambda s: writes.append(s))
    monkeypatch.setattr(_auto, "_mark_escalated", lambda sid: marked.append(sid))
    monkeypatch.setattr(_auto, "notify", lambda *a: None)
    monkeypatch.setattr(_auto.subprocess, "run",
                        lambda *a, **k: MagicMock(returncode=1, stdout="", stderr="boom"))
    monkeypatch.setattr(_auto.threading, "Thread", _SyncThread)

    assert _auto.run_escalation("sub-1", "m", "p", "2025-11-04", "hi") is True
    assert marked == []
    assert writes[-1]["status"] == "failed"


def test_run_escalation_materializes_pdf_to_temp_file(monkeypatch):
    _idle(monkeypatch)
    monkeypatch.setattr(_auto, "_write_escalation", lambda s: None)
    monkeypatch.setattr(_auto, "_mark_escalated", lambda sid: None)
    monkeypatch.setattr(_auto.threading, "Thread", _SyncThread)

    class FakeStorage:
        def get(self, key):
            assert key == "sub-1/claim.pdf"
            return b"%PDF-1.4 fake"

    monkeypatch.setattr(_auto, "get_storage", lambda: FakeStorage())

    captured: dict = {}

    def fake_run(*a, **k):
        path = k["env"].get("IH_PDF_PATH")
        captured["path"] = path
        captured["exists_during"] = bool(path) and os.path.exists(path)
        captured["content"] = open(path, "rb").read() if path else None
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_auto.subprocess, "run", fake_run)

    assert _auto.run_escalation(
        "sub-1", "m", "p", "2025-11-04", "msg", pdf_key="sub-1/claim.pdf"
    ) is True
    assert captured["exists_during"] is True
    assert captured["content"] == b"%PDF-1.4 fake"
    # Temp file is cleaned up after the subprocess returns.
    assert not os.path.exists(captured["path"])


def test_run_escalation_without_pdf_sets_empty_path(monkeypatch):
    _idle(monkeypatch)
    monkeypatch.setattr(_auto, "_write_escalation", lambda s: None)
    monkeypatch.setattr(_auto, "_mark_escalated", lambda sid: None)
    monkeypatch.setattr(_auto.threading, "Thread", _SyncThread)

    captured: dict = {}
    monkeypatch.setattr(_auto.subprocess, "run",
                        lambda *a, **k: captured.update(env=k["env"]) or
                        MagicMock(returncode=0, stdout="", stderr=""))

    assert _auto.run_escalation("sub-1", "m", "p", "2025-11-04", "msg") is True
    assert captured["env"]["IH_PDF_PATH"] == ""


def test_mark_escalated_sets_timestamp(db, make_submission):
    sub = make_submission()
    factory = sessionmaker(bind=db.get_bind())
    _auto._mark_escalated(sub.id, session_factory=factory)
    db.expire_all()
    refreshed = db.get(Submission, sub.id)
    assert refreshed.escalated_at is not None
