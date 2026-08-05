from unittest.mock import patch


def test_file_with_anthem_run_starts(client, make_submission):
    sub = make_submission(member_name="Nolan", pdf_path="k/claim.pdf")
    with patch("app.automation.run_claim_filing", return_value=True) as mock_run:
        r = client.post(f"/api/submissions/{sub.id}/file-with-anthem/run")
    assert r.status_code == 202
    assert "started" in r.json()["detail"].lower()
    # The runner is fed the submission's own fields, never client input.
    kwargs = mock_run.call_args.kwargs
    assert kwargs["submission_id"] == sub.id
    assert kwargs["member_name"] == "Nolan"
    assert kwargs["pdf_key"] == "k/claim.pdf"


def test_file_with_anthem_run_busy(client, make_submission):
    sub = make_submission(pdf_path="k/claim.pdf")
    with patch("app.automation.run_claim_filing", return_value=False):
        r = client.post(f"/api/submissions/{sub.id}/file-with-anthem/run")
    assert r.status_code == 202
    assert "already running" in r.json()["detail"].lower()


def test_file_with_anthem_run_404(client):
    r = client.post("/api/submissions/nope/file-with-anthem/run")
    assert r.status_code == 404


def test_file_with_anthem_run_400_without_pdf(client, make_submission):
    """A PDF is the whole point of the wizard — enforced server-side, not just
    by the disabled button in the modal."""
    sub = make_submission(pdf_path=None)
    with patch("app.automation.run_claim_filing") as mock_run:
        r = client.post(f"/api/submissions/{sub.id}/file-with-anthem/run")
    assert r.status_code == 400
    assert "pdf" in r.json()["detail"].lower()
    mock_run.assert_not_called()


def test_claim_filing_status(client):
    state = {
        "status": "complete",
        "submission_id": "sub-1",
        "last_run_at": "2026-08-05T12:00:00+00:00",
        "summary": {"returncode": 0, "stdout": "Done.", "stderr": ""},
    }
    with patch("app.automation.get_claim_filing_status", return_value=state):
        r = client.get("/api/claim-filing/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert body["submission_id"] == "sub-1"
    assert body["summary"]["stdout"] == "Done."
