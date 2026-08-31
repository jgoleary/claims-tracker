from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.database import _migrate


def _legacy_engine():
    """An on-disk-shaped DB whose anthem_claims rows still say "Deleted".

    Mirrors the live schema: SQLAlchemy renders the status Enum as a plain
    VARCHAR with no CHECK constraint, so the legacy word is storable.
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE anthem_claims ("
            "claim_number TEXT PRIMARY KEY, status VARCHAR(8) NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO anthem_claims (claim_number, status) VALUES "
            "('CLM-001', 'Deleted'), ('CLM-002', 'Approved'), ('CLM-003', 'Deleted')"
        ))
    return engine


def _statuses(engine):
    with engine.begin() as conn:
        return dict(conn.execute(text(
            "SELECT claim_number, status FROM anthem_claims ORDER BY claim_number"
        )).all())


def test_migrate_rewrites_deleted_to_missing_info():
    engine = _legacy_engine()
    _migrate(engine)
    assert _statuses(engine) == {
        "CLM-001": "Missing Info",
        "CLM-002": "Approved",
        "CLM-003": "Missing Info",
    }


def test_migrate_is_idempotent():
    engine = _legacy_engine()
    _migrate(engine)
    _migrate(engine)
    assert _statuses(engine) == {
        "CLM-001": "Missing Info",
        "CLM-002": "Approved",
        "CLM-003": "Missing Info",
    }


def test_migrate_tolerates_missing_table():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    _migrate(engine)  # must not raise
