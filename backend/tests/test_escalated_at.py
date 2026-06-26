from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.database import _migrate


def test_submission_response_includes_escalated_at(client, make_submission):
    make_submission()
    resp = client.get("/api/submissions?year=2025")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows
    assert "escalated_at" in rows[0]
    assert rows[0]["escalated_at"] is None


def test_migrate_adds_escalated_at_to_legacy_table():
    # Simulate an existing on-disk DB whose submissions table predates the column.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE submissions (id TEXT PRIMARY KEY, member_name TEXT)"
        ))

    cols = {c["name"] for c in inspect(engine).get_columns("submissions")}
    assert "escalated_at" not in cols

    _migrate(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("submissions")}
    assert "escalated_at" in cols

    # Idempotent — running again must not raise.
    _migrate(engine)
