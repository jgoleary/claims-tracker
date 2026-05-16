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
