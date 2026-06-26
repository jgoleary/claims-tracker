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


def _idle(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle", "submission_id": None})


# ── single-flight ────────────────────────────────────────────────────────────

def test_any_running_true_when_refresh_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "running"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    assert _auto._any_running() is True


def test_run_escalation_refuses_when_refresh_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "running"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "idle"})
    assert _auto.run_escalation("s1", "m", "p", "2025-01-01", "msg") is False


def test_run_escalation_refuses_when_escalation_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "running"})
    assert _auto.run_escalation("s1", "m", "p", "2025-01-01", "msg") is False


def test_run_automation_refuses_when_escalation_running(monkeypatch):
    monkeypatch.setattr(_auto, "_read", lambda: {"status": "idle"})
    monkeypatch.setattr(_auto, "_read_escalation", lambda: {"status": "running"})
    assert _auto.run_automation("u", "p") is False


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


def test_mark_escalated_sets_timestamp(db, make_submission):
    sub = make_submission()
    factory = sessionmaker(bind=db.get_bind())
    _auto._mark_escalated(sub.id, session_factory=factory)
    db.expire_all()
    refreshed = db.get(Submission, sub.id)
    assert refreshed.escalated_at is not None
