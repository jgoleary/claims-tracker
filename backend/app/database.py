from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATABASE_URL = f"sqlite:///{_DATA_DIR / 'claims.db'}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session, closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate(eng=engine) -> None:
    """Apply lightweight, idempotent column additions that create_all can't do.

    SQLAlchemy's create_all only creates missing tables, never ALTERs existing
    ones, so columns added to a model after a DB was first created need a manual
    ALTER. Each step checks the live schema first and is safe to run repeatedly.
    """
    inspector = inspect(eng)
    if "submissions" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("submissions")}
        if "escalated_at" not in cols:
            with eng.begin() as conn:
                conn.execute(text("ALTER TABLE submissions ADD COLUMN escalated_at DATETIME"))


def init_db() -> None:
    """Create all tables, then apply migrations. Safe to call multiple times."""
    from app.models import Base
    Base.metadata.create_all(bind=engine)
    _migrate()
