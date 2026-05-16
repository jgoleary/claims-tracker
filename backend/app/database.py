from pathlib import Path
from sqlalchemy import create_engine
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


def init_db() -> None:
    """Create all tables. Safe to call multiple times."""
    from app.models import Base
    Base.metadata.create_all(bind=engine)
