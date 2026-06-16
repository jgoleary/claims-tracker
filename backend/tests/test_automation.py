from unittest.mock import patch


def test_run_automation_starts(client):
    with patch("app.automation.run_automation", return_value=True) as mock_run:
        resp = client.post("/api/automation/run")
    assert resp.status_code == 202
    assert "started" in resp.json()["detail"]
    mock_run.assert_called_once()


def test_run_automation_already_running(client):
    with patch("app.automation.run_automation", return_value=False):
        resp = client.post("/api/automation/run")
    assert resp.status_code == 202
    assert "already running" in resp.json()["detail"]


def test_get_status_idle(client):
    with patch("app.automation.get_status", return_value={
        "status": "idle", "last_run_at": None, "summary": None
    }):
        resp = client.get("/api/automation/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"
    assert resp.json()["last_run_at"] is None


def test_get_status_complete(client):
    with patch("app.automation.get_status", return_value={
        "status": "complete",
        "last_run_at": "2025-11-15T10:00:00+00:00",
        "summary": {"returncode": 0},
    }):
        resp = client.get("/api/automation/status")
    assert resp.json()["status"] == "complete"
    assert resp.json()["last_run_at"] is not None


from unittest.mock import patch as _patch

from app import automation as _auto


def test_resolve_credentials_prefers_args():
    assert _auto._resolve_credentials("u", "p") == ("u", "p")


def test_resolve_credentials_falls_back_to_keychain():
    with _patch("app.automation.credentials.get_credentials", return_value=("k", "kp")):
        assert _auto._resolve_credentials("", "") == ("k", "kp")


def test_resolve_credentials_none_when_unset():
    with _patch("app.automation.credentials.get_credentials", return_value=None):
        assert _auto._resolve_credentials("", "") is None


def test_classify_failure_detects_mfa():
    msg = _auto._classify_failure({"stdout": "[auth] ERROR: TimeoutError 120000ms", "stderr": ""})
    assert "MFA" in msg


def test_classify_failure_generic():
    msg = _auto._classify_failure({"stdout": "[claims] ERROR: bad selector", "stderr": ""})
    assert "MFA" not in msg
    assert "failed" in msg.lower()


def test_classify_failure_process_timeout_is_generic():
    msg = _auto._classify_failure({"error": "timed out after 300s"})
    assert "MFA" not in msg


def test_notify_swallows_errors():
    with _patch("app.automation.subprocess.run", side_effect=OSError("no osascript")):
        _auto.notify("t", "m")  # must not raise
