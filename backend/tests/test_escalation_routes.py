from unittest.mock import patch


def test_escalate_draft_returns_message(client, make_submission, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("app.escalation.credentials.get_anthropic_key", lambda: None)
    sub = make_submission()
    resp = client.post(f"/api/submissions/{sub.id}/escalate/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "template"
    assert body["configured"] is False
    assert body["message"].strip()
    assert sub.provider_name in body["message"]


def test_escalate_draft_404(client):
    resp = client.post("/api/submissions/does-not-exist/escalate/draft")
    assert resp.status_code == 404


def test_escalate_run_starts(client, make_submission):
    sub = make_submission()
    with patch("app.automation.run_escalation", return_value=True) as mock_run:
        resp = client.post(f"/api/submissions/{sub.id}/escalate/run", json={"message": "hello"})
    assert resp.status_code == 202
    assert "started" in resp.json()["detail"].lower()
    mock_run.assert_called_once()
    # The submission's own fields are passed to the runner, not arbitrary input.
    kwargs = mock_run.call_args.kwargs
    assert kwargs["submission_id"] == sub.id
    assert kwargs["message"] == "hello"
    assert kwargs["provider_name"] == sub.provider_name


def test_escalate_run_busy(client, make_submission):
    sub = make_submission()
    with patch("app.automation.run_escalation", return_value=False):
        resp = client.post(f"/api/submissions/{sub.id}/escalate/run", json={"message": "hi"})
    assert resp.status_code == 202
    assert "already running" in resp.json()["detail"].lower()


def test_escalate_run_404(client):
    resp = client.post("/api/submissions/nope/escalate/run", json={"message": "hi"})
    assert resp.status_code == 404


def test_escalation_status(client):
    with patch("app.automation.get_escalation_status", return_value={
        "status": "running", "submission_id": "s1", "last_run_at": None, "summary": None,
    }):
        resp = client.get("/api/escalations/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["submission_id"] == "s1"
