# Claims Tracker — Backend Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Working, fully-tested Python package containing the DB models, matching engine,
and ingest logic — no FastAPI dependency, exercisable with pytest alone.

**Architecture:** SQLAlchemy 2.0 ORM with SQLite. Pure Python modules for matching and
ingest with no web framework dependency so they can be unit tested in isolation. The
FastAPI API layer (Plan 2) imports these modules and wires them to HTTP routes.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0, pytest, no async (sync SQLAlchemy + sync
FastAPI in Plan 2)

---

## File Map

```
claims-tracker/
  .gitignore
  README.md
  backend/
    requirements.txt          # runtime deps
    requirements-dev.txt      # test deps
    pyproject.toml            # pytest config only
    app/
      __init__.py
      config.py               # thresholds + plan year constants
      database.py             # engine, SessionLocal, get_db(), init_db()
      models.py               # SQLAlchemy ORM models (all 5 tables)
      storage.py              # Storage ABC + LocalFileStorage
      matching.py             # normalize(), _provider_matches(), run_matching()
      ingest.py               # ingest_claims_csv(), ingest_benefits(), parsing utils
    tests/
      __init__.py
      conftest.py             # in-memory SQLite fixtures + factories
      test_models.py          # smoke test: can create rows for each table
      test_storage.py         # LocalFileStorage save/get/delete
      test_matching.py        # normalize, provider matching, run_matching tiers
      test_ingest.py          # CSV parsing utils, ingest_claims_csv, ingest_benefits
  data/                       # gitignored
```

---

## Task 1: Project Scaffold

**Files:**

- Create: `.gitignore`
- Create: `README.md`
- Create: `backend/requirements.txt`
- Create: `backend/requirements-dev.txt`
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `data/.gitkeep`

- [ ] **Step 1: Initialize git and create directory structure**

```bash
cd /Users/jgoleary/coding/claims-tracker
git init
mkdir -p backend/app backend/tests data/pdfs data/exports docs/superpowers/plans docs/superpowers/specs
touch backend/app/__init__.py backend/tests/__init__.py data/.gitkeep
```

- [ ] **Step 2: Write `.gitignore`**

```
# Python
__pycache__/
*.pyc
*.pyo
.venv/
*.egg-info/
.pytest_cache/
.ruff_cache/

# Data (never commit)
data/

# Frontend build
frontend/dist/
frontend/node_modules/

# Superpowers visual companion
.superpowers/

# OS
.DS_Store
```

- [ ] **Step 3: Write `backend/requirements.txt`**

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
sqlalchemy>=2.0.0
pydantic>=2.0.0
python-multipart>=0.0.9
```

- [ ] **Step 4: Write `backend/requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0.0
httpx>=0.27.0
```

- [ ] **Step 5: Write `backend/pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 6: Write `README.md`**

````markdown
# Claims Tracker

Local web app to track OON medical claims submitted to Anthem.

## Development

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload  # after Plan 2
```
````

### Frontend

```bash
cd frontend
npm install && npm run dev  # after Plan 3
```

### Automation

```bash
cd automation
python fetch_all.py  # prompts for credentials, opens Chromium
```

````

- [ ] **Step 7: Install dependencies and verify Python version**

```bash
cd backend
python3 --version  # must be 3.11+
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
````

Expected: pip installs without errors.

- [ ] **Step 8: Commit**

```bash
git add .gitignore README.md backend/ data/.gitkeep docs/
git commit -m "feat: project scaffold"
```

---

## Task 2: Config and Database

**Files:**

- Create: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Write `backend/app/config.py`**

```python
from datetime import date

# Alert thresholds
MISSING_DAYS = 30
STALE_PENDING_DAYS = 45
UNDERPAID_MIN_CENTS = 2_500   # $25.00
UNDERPAID_PCT = 0.10          # 10%
TOTALS_DRIFT_THRESHOLD_CENTS = 5_000  # $50.00

# Plan year (update each January)
PLAN_YEAR_START = date(2025, 1, 1)
PLAN_YEAR_END = date(2025, 12, 31)
```

- [ ] **Step 2: Write `backend/app/database.py`**

```python
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
```

- [ ] **Step 3: Write `backend/tests/conftest.py`**

```python
import pytest
import uuid
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Submission, AnthemClaim


@pytest.fixture(scope="function")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture
def make_submission(db: Session):
    def factory(
        member_name: str = "James OLeary",
        provider_name: str = "Joyful Behavior Therapy",
        service_date: date = date(2025, 11, 4),
        amount_billed: int = 240_000,
        expected_reimbursement: int = 180_000,
        network_treatment: str = "out_of_network",
        submitted_date: date = date(2025, 11, 10),
        submission_method: str = "portal",
    ) -> Submission:
        s = Submission(
            id=str(uuid.uuid4()),
            member_name=member_name,
            provider_name=provider_name,
            service_date=service_date,
            amount_billed=amount_billed,
            expected_reimbursement=expected_reimbursement,
            network_treatment=network_treatment,
            submitted_date=submitted_date,
            submission_method=submission_method,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s
    return factory


@pytest.fixture
def make_claim(db: Session):
    def factory(
        claim_number: str = "CLM-001",
        patient_name: str = "James OLeary",
        service_date: date = date(2025, 11, 4),
        status: str = "Pending",
        provider_name: str = "Joyful Behavior Therapy",
        claim_type: str = "Medical",
        billed: int = 240_000,
        plan_discount: int = 0,
        allowed: int = 240_000,
        plan_paid: int = 0,
        additional_savings: int = 0,
        deductible: int = 0,
        coinsurance: int = 0,
        copay: int = 0,
        not_covered: int = 0,
        your_cost: int = 0,
    ) -> AnthemClaim:
        c = AnthemClaim(
            claim_number=claim_number,
            claim_type=claim_type,
            patient_name=patient_name,
            service_date=service_date,
            status=status,
            provider_name=provider_name,
            billed=billed,
            plan_discount=plan_discount,
            allowed=allowed,
            plan_paid=plan_paid,
            additional_savings=additional_savings,
            deductible=deductible,
            coinsurance=coinsurance,
            copay=copay,
            not_covered=not_covered,
            your_cost=your_cost,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return c
    return factory
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/app/database.py backend/tests/conftest.py
git commit -m "feat: config constants and database session setup"
```

---

## Task 3: SQLAlchemy Models

**Files:**

- Create: `backend/app/models.py`
- Create: `backend/tests/test_models.py`

- [ ] **Step 1: Write failing smoke test**

`backend/tests/test_models.py`:

```python
import uuid
from datetime import date, datetime
from sqlalchemy.orm import Session

from app.models import (
    Submission, AnthemClaim, Match, ProviderAlias, BenefitsSnapshot
)


def test_create_submission(db: Session):
    s = Submission(
        id=str(uuid.uuid4()),
        member_name="James OLeary",
        provider_name="Joyful Behavior Therapy",
        service_date=date(2025, 11, 4),
        amount_billed=240_000,
        expected_reimbursement=180_000,
        network_treatment="out_of_network",
        submitted_date=date(2025, 11, 10),
        submission_method="portal",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    assert db.get(Submission, s.id) is not None


def test_create_anthem_claim(db: Session):
    c = AnthemClaim(
        claim_number="CLM-001",
        claim_type="Medical",
        patient_name="James OLeary",
        service_date=date(2025, 11, 4),
        status="Pending",
        provider_name="Joyful Behavior Therapy",
        billed=240_000,
        plan_discount=0,
        allowed=240_000,
        plan_paid=0,
        additional_savings=0,
        deductible=0,
        coinsurance=0,
        copay=0,
        not_covered=0,
        your_cost=0,
    )
    db.add(c)
    db.commit()
    assert db.get(AnthemClaim, "CLM-001") is not None


def test_create_match(db: Session, make_submission, make_claim):
    s = make_submission()
    c = make_claim()
    m = Match(
        submission_id=s.id,
        anthem_claim_number=c.claim_number,
        match_type="auto",
    )
    db.add(m)
    db.commit()
    assert db.get(Match, s.id) is not None


def test_create_provider_alias(db: Session):
    a = ProviderAlias(canonical_name="joyful behavior therapy", anthem_name="joyful behavior therapy l")
    db.add(a)
    db.commit()
    assert a.id is not None


def test_create_benefits_snapshot(db: Session):
    snap = BenefitsSnapshot(
        snapshot_date=datetime(2025, 11, 15),
        network="out_of_network",
        deductible_limit=300_000,
        deductible_spent=150_000,
        oop_limit=600_000,
        oop_spent=200_000,
    )
    db.add(snap)
    db.commit()
    assert snap.id is not None
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && source .venv/bin/activate
pytest tests/test_models.py -v
```

Expected: `ImportError: cannot import name 'Submission' from 'app.models'`

- [ ] **Step 3: Write `backend/app/models.py`**

```python
import enum
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date, DateTime, Enum as SAEnum, ForeignKey, Integer,
    String, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    member_name: Mapped[str] = mapped_column(String, nullable=False)
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_billed: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_reimbursement: Mapped[int] = mapped_column(Integer, nullable=False)
    network_treatment: Mapped[str] = mapped_column(
        SAEnum("in_network_exception", "out_of_network", name="network_treatment"),
        nullable=False,
    )
    submitted_date: Mapped[date] = mapped_column(Date, nullable=False)
    submission_method: Mapped[str] = mapped_column(
        SAEnum("portal", "email", name="submission_method"),
        nullable=False,
    )
    pdf_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    match: Mapped[Optional["Match"]] = relationship("Match", back_populates="submission", uselist=False)


class AnthemClaim(Base):
    __tablename__ = "anthem_claims"

    claim_number: Mapped[str] = mapped_column(String, primary_key=True)
    claim_type: Mapped[str] = mapped_column(String, nullable=False)
    patient_name: Mapped[str] = mapped_column(String, nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    received_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    processed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum("Pending", "Approved", "Denied", name="claim_status"),
        nullable=False,
    )
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    billed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_discount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    additional_savings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deductible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coinsurance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    copay: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_covered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    your_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    match: Mapped[Optional["Match"]] = relationship("Match", back_populates="anthem_claim", uselist=False)


class Match(Base):
    __tablename__ = "matches"

    submission_id: Mapped[str] = mapped_column(
        String, ForeignKey("submissions.id"), primary_key=True
    )
    anthem_claim_number: Mapped[str] = mapped_column(
        String, ForeignKey("anthem_claims.claim_number"), nullable=False
    )
    match_type: Mapped[str] = mapped_column(
        SAEnum("auto", "confirmed", "manual", name="match_type"),
        nullable=False,
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    submission: Mapped["Submission"] = relationship("Submission", back_populates="match")
    anthem_claim: Mapped["AnthemClaim"] = relationship("AnthemClaim", back_populates="match")


class ProviderAlias(Base):
    __tablename__ = "provider_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String, nullable=False)
    anthem_name: Mapped[str] = mapped_column(String, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("canonical_name", "anthem_name"),)


class BenefitsSnapshot(Base):
    __tablename__ = "benefits_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    network: Mapped[str] = mapped_column(
        SAEnum("in_network", "out_of_network", name="network"),
        nullable=False,
    )
    deductible_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    deductible_spent: Mapped[int] = mapped_column(Integer, nullable=False)
    oop_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    oop_spent: Mapped[int] = mapped_column(Integer, nullable=False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_models.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: SQLAlchemy models for all five tables"
```

---

## Task 4: Storage Interface

**Files:**

- Create: `backend/app/storage.py`
- Create: `backend/tests/test_storage.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/test_storage.py`:

```python
import pytest
from pathlib import Path
from app.storage import LocalFileStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "pdfs")


def test_save_and_get(storage: LocalFileStorage):
    key = storage.save("sub-123/bill.pdf", b"PDF content here")
    assert key == "sub-123/bill.pdf"
    assert storage.get("sub-123/bill.pdf") == b"PDF content here"


def test_get_missing_raises(storage: LocalFileStorage):
    with pytest.raises(FileNotFoundError):
        storage.get("nonexistent/file.pdf")


def test_delete(storage: LocalFileStorage):
    storage.save("sub-123/bill.pdf", b"data")
    storage.delete("sub-123/bill.pdf")
    with pytest.raises(FileNotFoundError):
        storage.get("sub-123/bill.pdf")


def test_delete_missing_is_noop(storage: LocalFileStorage):
    storage.delete("nonexistent/file.pdf")  # must not raise


def test_save_creates_subdirectories(storage: LocalFileStorage):
    storage.save("a/b/c/file.pdf", b"nested")
    assert storage.get("a/b/c/file.pdf") == b"nested"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_storage.py -v
```

Expected: `ImportError: cannot import name 'LocalFileStorage' from 'app.storage'`

- [ ] **Step 3: Write `backend/app/storage.py`**

```python
from abc import ABC, abstractmethod
from pathlib import Path


class Storage(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        """Persist data under key; returns the key."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve data by key; raises FileNotFoundError if absent."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove data by key; no-op if absent."""


class LocalFileStorage(Storage):
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        path = self.base_dir / key
        if not path.exists():
            raise FileNotFoundError(f"No file at storage key: {key!r}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self.base_dir / key
        if path.exists():
            path.unlink()


_default_storage: Storage | None = None


def get_storage() -> Storage:
    """Return the process-wide storage instance (lazy init)."""
    global _default_storage
    if _default_storage is None:
        from pathlib import Path as _Path
        _default_storage = LocalFileStorage(
            _Path(__file__).parent.parent.parent / "data" / "pdfs"
        )
    return _default_storage
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_storage.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage.py backend/tests/test_storage.py
git commit -m "feat: Storage interface and LocalFileStorage implementation"
```

---

## Task 5: Matching Engine — normalize() and Provider Matching

**Files:**

- Create: `backend/app/matching.py` (partial — normalize and \_provider_matches only)
- Create: `backend/tests/test_matching.py` (partial)

- [ ] **Step 1: Write failing tests for normalize()**

`backend/tests/test_matching.py`:

```python
import pytest
from app.matching import normalize, _provider_matches


class TestNormalize:
    def test_lowercases(self):
        assert normalize("JOYFUL BEHAVIOR") == "joyful behavior"

    def test_strips_leading_trailing_whitespace(self):
        assert normalize("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self):
        assert normalize("joyful  behavior   therapy") == "joyful behavior therapy"

    def test_strips_punctuation(self):
        assert normalize("St. Mary's") == "st marys"

    def test_strips_special_chars(self):
        assert normalize("O'Leary, James") == "oleary james"

    def test_keeps_numbers(self):
        assert normalize("Provider 123") == "provider 123"

    def test_empty_string(self):
        assert normalize("") == ""
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_matching.py::TestNormalize -v
```

Expected: `ImportError: cannot import name 'normalize' from 'app.matching'`

- [ ] **Step 3: Write `backend/app/matching.py` with normalize() and
      \_provider_matches()**

```python
import re
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import select, exists

from app.models import Submission, AnthemClaim, Match, ProviderAlias


def normalize(s: str) -> str:
    """Lowercase, collapse whitespace, strip non-alphanumeric except spaces."""
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return s


def _provider_matches(
    sub_provider: str,
    claim_provider: str,
    alias_pairs: list[tuple[str, str]],
) -> bool:
    """True if providers match by exact name, prefix, or known alias."""
    n_sub = normalize(sub_provider)
    n_claim = normalize(claim_provider)

    if n_sub == n_claim:
        return True
    if n_sub.startswith(n_claim) or n_claim.startswith(n_sub):
        return True
    for canonical, anthem in alias_pairs:
        if canonical == n_sub and anthem == n_claim:
            return True
    return False


@dataclass
class MatchResult:
    auto_matched: list[tuple[str, str]] = field(default_factory=list)
    suggestions: list[tuple[str, list[str]]] = field(default_factory=list)


def run_matching(db: Session) -> MatchResult:
    # Implemented in Task 6
    raise NotImplementedError
```

- [ ] **Step 4: Write failing tests for \_provider_matches()**

Append to `backend/tests/test_matching.py`:

```python
class TestProviderMatches:
    def test_exact_match(self):
        assert _provider_matches("Joyful Behavior Therapy", "Joyful Behavior Therapy", [])

    def test_exact_match_case_insensitive(self):
        assert _provider_matches("JOYFUL BEHAVIOR", "joyful behavior", [])

    def test_prefix_match_claim_truncated(self):
        # Anthem truncates at ~25 chars
        assert _provider_matches("Joyful Behavior Therapy LLC", "Joyful Behavior Therapy L", [])

    def test_prefix_match_submission_shorter(self):
        assert _provider_matches("California Pacific", "California Pacific Medical Center", [])

    def test_alias_match(self):
        aliases = [("citrus speech", "citrus speech and language")]
        assert _provider_matches("Citrus Speech", "Citrus Speech and Language", aliases)

    def test_no_match(self):
        assert not _provider_matches("Dr. Smith", "Joyful Behavior Therapy", [])

    def test_alias_wrong_direction_no_match(self):
        # Aliases are directional: canonical -> anthem
        aliases = [("citrus speech", "citrus speech and language")]
        assert not _provider_matches("Citrus Speech and Language", "Citrus Speech", aliases)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_matching.py -v
```

Expected: All normalize and \_provider_matches tests pass. `run_matching` tests don't
exist yet.

- [ ] **Step 6: Commit**

```bash
git add backend/app/matching.py backend/tests/test_matching.py
git commit -m "feat: matching engine normalize() and provider matching"
```

---

## Task 6: Matching Engine — run_matching()

**Files:**

- Modify: `backend/app/matching.py` (implement run_matching)
- Modify: `backend/tests/test_matching.py` (add run_matching tests)

- [ ] **Step 1: Write failing tests for run_matching()**

Append to `backend/tests/test_matching.py`:

```python
from sqlalchemy.orm import Session
from app.models import Match, ProviderAlias
from app.matching import run_matching
from datetime import date


class TestRunMatching:
    def test_auto_match_exact_provider(self, db: Session, make_submission, make_claim):
        sub = make_submission()
        claim = make_claim()
        result = run_matching(db)
        assert len(result.auto_matched) == 1
        assert result.auto_matched[0] == (sub.id, claim.claim_number)
        assert db.get(Match, sub.id) is not None

    def test_auto_match_prefix_provider(self, db: Session, make_submission, make_claim):
        sub = make_submission(provider_name="Joyful Behavior Therapy LLC")
        claim = make_claim(provider_name="Joyful Behavior Therapy L")
        result = run_matching(db)
        assert len(result.auto_matched) == 1

    def test_auto_match_via_alias(self, db: Session, make_submission, make_claim):
        alias = ProviderAlias(
            canonical_name="citrus speech",
            anthem_name="citrus speech and language",
        )
        db.add(alias)
        db.commit()
        sub = make_submission(provider_name="Citrus Speech")
        claim = make_claim(provider_name="Citrus Speech and Language")
        result = run_matching(db)
        assert len(result.auto_matched) == 1

    def test_no_match_different_date(self, db: Session, make_submission, make_claim):
        make_submission(service_date=date(2025, 11, 4))
        make_claim(service_date=date(2025, 10, 1))
        result = run_matching(db)
        assert result.auto_matched == []
        assert result.suggestions == []

    def test_no_match_different_member(self, db: Session, make_submission, make_claim):
        make_submission(member_name="James OLeary")
        make_claim(patient_name="Nolan OLeary")
        result = run_matching(db)
        assert result.auto_matched == []
        assert result.suggestions == []

    def test_tier1_conflict_becomes_suggestion(self, db: Session, make_submission, make_claim):
        sub = make_submission()
        claim1 = make_claim(claim_number="CLM-001")
        claim2 = make_claim(claim_number="CLM-002")
        result = run_matching(db)
        assert result.auto_matched == []
        assert len(result.suggestions) == 1
        assert set(result.suggestions[0][1]) == {"CLM-001", "CLM-002"}

    def test_tier2_suggestion_provider_mismatch(self, db: Session, make_submission, make_claim):
        sub = make_submission(provider_name="Dr. Smith Psychiatry")
        claim = make_claim(provider_name="Smith John MD")
        result = run_matching(db)
        assert result.auto_matched == []
        assert len(result.suggestions) == 1
        assert result.suggestions[0][0] == sub.id

    def test_already_matched_submission_skipped(self, db: Session, make_submission, make_claim):
        sub = make_submission()
        claim = make_claim()
        db.add(Match(submission_id=sub.id, anthem_claim_number=claim.claim_number, match_type="manual"))
        db.commit()
        result = run_matching(db)
        assert result.auto_matched == []

    def test_already_matched_claim_skipped(self, db: Session, make_submission, make_claim):
        sub1 = make_submission(provider_name="Provider A")
        sub2 = make_submission(provider_name="Provider A")
        claim = make_claim(provider_name="Provider A")
        db.add(Match(submission_id=sub1.id, anthem_claim_number=claim.claim_number, match_type="manual"))
        db.commit()
        result = run_matching(db)
        # claim is already matched, sub2 should get no match
        assert result.auto_matched == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_matching.py::TestRunMatching -v
```

Expected: `NotImplementedError`

- [ ] **Step 3: Implement run_matching() in `backend/app/matching.py`**

Replace the `run_matching` stub with:

```python
def run_matching(db: Session) -> MatchResult:
    result = MatchResult()

    unmatched_submissions = db.scalars(
        select(Submission).where(
            ~exists().where(Match.submission_id == Submission.id)
        )
    ).all()

    unmatched_claims = db.scalars(
        select(AnthemClaim).where(
            ~exists().where(Match.anthem_claim_number == AnthemClaim.claim_number)
        )
    ).all()

    aliases = [
        (a.canonical_name, a.anthem_name)
        for a in db.scalars(select(ProviderAlias)).all()
    ]

    newly_matched_claims: set[str] = set()

    for submission in unmatched_submissions:
        norm_member = normalize(submission.member_name)

        candidates = [
            c for c in unmatched_claims
            if c.claim_number not in newly_matched_claims
            and c.service_date == submission.service_date
            and normalize(c.patient_name) == norm_member
        ]

        if not candidates:
            continue

        tier1 = [
            c for c in candidates
            if _provider_matches(submission.provider_name, c.provider_name, aliases)
        ]

        if len(tier1) == 1:
            db.add(Match(
                submission_id=submission.id,
                anthem_claim_number=tier1[0].claim_number,
                match_type="auto",
            ))
            newly_matched_claims.add(tier1[0].claim_number)
            result.auto_matched.append((submission.id, tier1[0].claim_number))
        elif len(tier1) > 1:
            result.suggestions.append((submission.id, [c.claim_number for c in tier1]))
        else:
            result.suggestions.append((submission.id, [c.claim_number for c in candidates]))

    db.commit()
    return result
```

- [ ] **Step 4: Run all matching tests**

```bash
pytest tests/test_matching.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/matching.py backend/tests/test_matching.py
git commit -m "feat: run_matching() with auto, suggestion, and conflict handling"
```

---

## Task 7: CSV Parsing Utilities

**Files:**

- Create: `backend/app/ingest.py` (parsing utils only)
- Create: `backend/tests/test_ingest.py` (parsing tests only)

- [ ] **Step 1: Write failing tests**

`backend/tests/test_ingest.py`:

```python
import pytest
from app.ingest import _parse_money, _parse_date, _parse_patient_name, _normalize_status
from datetime import date


class TestParseMoney:
    def test_dollar_sign_and_commas(self):
        assert _parse_money("$1,190.00") == 119_000

    def test_plain_number(self):
        assert _parse_money("350.00") == 35_000

    def test_zero(self):
        assert _parse_money("$0.00") == 0

    def test_empty_string(self):
        assert _parse_money("") == 0

    def test_not_available(self):
        assert _parse_money("Not Available") == 0

    def test_quoted_value(self):
        assert _parse_money('"$2,400.00"') == 240_000


class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2025-11-04") == date(2025, 11, 4)

    def test_not_available(self):
        assert _parse_date("Not Available") is None

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_strips_whitespace(self):
        assert _parse_date("  2025-11-04  ") == date(2025, 11, 4)


class TestParsePatientName:
    def test_strips_dob(self):
        assert _parse_patient_name("Nolan O'leary (2019-02-14)") == "Nolan O'leary"

    def test_no_dob(self):
        assert _parse_patient_name("James OLeary") == "James OLeary"

    def test_strips_whitespace(self):
        assert _parse_patient_name("  James OLeary  ") == "James OLeary"


class TestNormalizeStatus:
    def test_pending(self):
        assert _normalize_status("Pending") == "Pending"

    def test_lowercase_approved(self):
        assert _normalize_status("approved") == "Approved"

    def test_uppercase_denied(self):
        assert _normalize_status("DENIED") == "Denied"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown claim status"):
            _normalize_status("Cancelled")
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_ingest.py -v
```

Expected: `ImportError: cannot import name '_parse_money' from 'app.ingest'`

- [ ] **Step 3: Write `backend/app/ingest.py` with parsing utilities**

```python
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AnthemClaim, BenefitsSnapshot
from app.matching import run_matching, MatchResult


def _parse_money(s: str) -> int:
    """Parse '$1,190.00' or '1190.00' or '' to integer cents."""
    s = s.strip().strip('"').lstrip('$').replace(',', '')
    if not s or s.lower() == 'not available':
        return 0
    return round(float(s) * 100)


def _parse_date(s: str) -> Optional[date]:
    """Parse 'YYYY-MM-DD' to date, or return None for empty/'Not Available'."""
    s = s.strip()
    if not s or s.lower() == 'not available':
        return None
    return date.fromisoformat(s)


def _parse_patient_name(s: str) -> str:
    """Parse 'Nolan O\'leary (2019-02-14)' -> 'Nolan O\'leary'."""
    s = s.strip()
    idx = s.rfind(' (')
    if idx != -1:
        return s[:idx]
    return s


def _normalize_status(s: str) -> str:
    """Normalize Anthem status to Pending/Approved/Denied."""
    normalized = s.strip().capitalize()
    if normalized not in ('Pending', 'Approved', 'Denied'):
        raise ValueError(f"Unknown claim status: {s!r}")
    return normalized


@dataclass
class IngestResult:
    new: int = 0
    updated: int = 0
    auto_matched: int = 0
    suggestions: int = 0


def ingest_claims_csv(db: Session, csv_bytes: bytes) -> IngestResult:
    # Implemented in Task 8
    raise NotImplementedError


def ingest_benefits(db: Session, data: dict) -> None:
    # Implemented in Task 8
    raise NotImplementedError
```

- [ ] **Step 4: Run parsing tests**

```bash
pytest tests/test_ingest.py::TestParseMoney tests/test_ingest.py::TestParseDate tests/test_ingest.py::TestParsePatientName tests/test_ingest.py::TestNormalizeStatus -v
```

Expected: All 16 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest.py backend/tests/test_ingest.py
git commit -m "feat: CSV parsing utilities (money, date, patient name, status)"
```

---

## Task 8: Ingest — ingest_claims_csv() and ingest_benefits()

**Files:**

- Modify: `backend/app/ingest.py` (implement the two ingest functions)
- Modify: `backend/tests/test_ingest.py` (add ingest tests)

- [ ] **Step 1: Write failing tests for ingest_claims_csv()**

Add these imports to the top of `backend/tests/test_ingest.py` (after the existing
imports):

```python
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.ingest import ingest_claims_csv, ingest_benefits
from app.models import AnthemClaim, BenefitsSnapshot, Match
```

Then append the following constants and test classes to the bottom of
`backend/tests/test_ingest.py`:

```python
SAMPLE_CSV = """\
Claim #,Type,Patient,Service Date,Status,Provider,Billed,Plan Discount,Allowed,Plan Paid,Additional Savings,Deductible,Coinsurance,Copay,Not Covered,Your Cost,Received Date,Processed Date
CLM-001,Medical,James OLeary (1985-03-12),2025-11-04,Pending,Joyful Behavior Therapy,2400.00,0.00,2400.00,0.00,0.00,0.00,0.00,0.00,0.00,0.00,2025-11-06,Not Available
CLM-002,Medical,Nolan OLeary (2019-02-14),2025-10-01,Approved,California Pacific Medica,"$1,190.00",0.00,"$1,190.00","$952.00",0.00,0.00,"$238.00",0.00,0.00,"$238.00",2025-10-03,2025-10-15
"""

SAMPLE_CSV_BOM = "﻿" + SAMPLE_CSV


class TestIngestClaimsCSV:
    def test_inserts_new_claims(self, db: Session):
        result = ingest_claims_csv(db, SAMPLE_CSV.encode())
        assert result.new == 2
        assert result.updated == 0
        claims = db.scalars(select(AnthemClaim)).all()
        assert len(claims) == 2

    def test_handles_bom(self, db: Session):
        result = ingest_claims_csv(db, SAMPLE_CSV_BOM.encode())
        assert result.new == 2

    def test_upserts_existing_claim(self, db: Session):
        ingest_claims_csv(db, SAMPLE_CSV.encode())
        # Ingest again — same claim numbers, should update not insert
        result = ingest_claims_csv(db, SAMPLE_CSV.encode())
        assert result.new == 0
        assert result.updated == 2
        assert len(db.scalars(select(AnthemClaim)).all()) == 2

    def test_parses_money_correctly(self, db: Session):
        ingest_claims_csv(db, SAMPLE_CSV.encode())
        clm2 = db.get(AnthemClaim, "CLM-002")
        assert clm2.billed == 119_000
        assert clm2.plan_paid == 95_200
        assert clm2.coinsurance == 23_800

    def test_parses_patient_name(self, db: Session):
        ingest_claims_csv(db, SAMPLE_CSV.encode())
        clm1 = db.get(AnthemClaim, "CLM-001")
        assert clm1.patient_name == "James OLeary"

    def test_triggers_matching(self, db: Session, make_submission):
        make_submission(
            member_name="James OLeary",
            provider_name="Joyful Behavior Therapy",
            service_date=date(2025, 11, 4),
        )
        result = ingest_claims_csv(db, SAMPLE_CSV.encode())
        assert result.auto_matched == 1
        match = db.scalars(select(Match)).first()
        assert match is not None
        assert match.match_type == "auto"


SAMPLE_BENEFITS = {
    "in_network": {
        "deductible_limit": "$1,500.00",
        "deductible_spent": "$750.00",
        "oop_limit": "$3,000.00",
        "oop_spent": "$1,200.00",
    },
    "out_of_network": {
        "deductible_limit": "$3,000.00",
        "deductible_spent": "$500.00",
        "oop_limit": "$6,000.00",
        "oop_spent": "$800.00",
    },
}


class TestIngestBenefits:
    def test_creates_two_snapshots(self, db: Session):
        ingest_benefits(db, SAMPLE_BENEFITS)
        snaps = db.scalars(select(BenefitsSnapshot)).all()
        assert len(snaps) == 2

    def test_parses_money_to_cents(self, db: Session):
        ingest_benefits(db, SAMPLE_BENEFITS)
        snaps = {s.network: s for s in db.scalars(select(BenefitsSnapshot)).all()}
        assert snaps["in_network"].deductible_limit == 150_000
        assert snaps["in_network"].deductible_spent == 75_000
        assert snaps["out_of_network"].oop_limit == 600_000

    def test_multiple_ingests_append_snapshots(self, db: Session):
        ingest_benefits(db, SAMPLE_BENEFITS)
        ingest_benefits(db, SAMPLE_BENEFITS)
        assert len(db.scalars(select(BenefitsSnapshot)).all()) == 4
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_ingest.py::TestIngestClaimsCSV tests/test_ingest.py::TestIngestBenefits -v
```

Expected: `NotImplementedError`

- [ ] **Step 3: Implement ingest_claims_csv() and ingest_benefits() in
      `backend/app/ingest.py`**

Replace the two `raise NotImplementedError` stubs:

```python
def ingest_claims_csv(db: Session, csv_bytes: bytes) -> IngestResult:
    text = csv_bytes.decode('utf-8-sig')  # utf-8-sig strips BOM if present
    reader = csv.DictReader(io.StringIO(text))

    now = datetime.utcnow()
    new_count = 0
    updated_count = 0

    for row in reader:
        claim_number = row['Claim #'].strip()
        existing = db.get(AnthemClaim, claim_number)

        fields = {
            'claim_type': row.get('Type', 'Medical').strip(),
            'patient_name': _parse_patient_name(row['Patient']),
            'service_date': _parse_date(row['Service Date']),
            'received_date': _parse_date(row.get('Received Date', '')),
            'processed_date': _parse_date(row.get('Processed Date', '')),
            'status': _normalize_status(row['Status']),
            'provider_name': row['Provider'].strip(),
            'billed': _parse_money(row.get('Billed', '0')),
            'plan_discount': _parse_money(row.get('Plan Discount', '0')),
            'allowed': _parse_money(row.get('Allowed', '0')),
            'plan_paid': _parse_money(row.get('Plan Paid', '0')),
            'additional_savings': _parse_money(row.get('Additional Savings', '0')),
            'deductible': _parse_money(row.get('Deductible', '0')),
            'coinsurance': _parse_money(row.get('Coinsurance', '0')),
            'copay': _parse_money(row.get('Copay', '0')),
            'not_covered': _parse_money(row.get('Not Covered', '0')),
            'your_cost': _parse_money(row.get('Your Cost', '0')),
            'last_seen_at': now,
        }

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            updated_count += 1
        else:
            db.add(AnthemClaim(claim_number=claim_number, first_seen_at=now, **fields))
            new_count += 1

    db.commit()

    match_result = run_matching(db)
    return IngestResult(
        new=new_count,
        updated=updated_count,
        auto_matched=len(match_result.auto_matched),
        suggestions=len(match_result.suggestions),
    )


def ingest_benefits(db: Session, data: dict) -> None:
    now = datetime.utcnow()
    for network_key, network_data in data.items():
        db.add(BenefitsSnapshot(
            snapshot_date=now,
            network=network_key,
            deductible_limit=_parse_money(str(network_data['deductible_limit'])),
            deductible_spent=_parse_money(str(network_data['deductible_spent'])),
            oop_limit=_parse_money(str(network_data['oop_limit'])),
            oop_spent=_parse_money(str(network_data['oop_spent'])),
        ))
    db.commit()
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests pass. Output ends with something like `32 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest.py backend/tests/test_ingest.py
git commit -m "feat: ingest_claims_csv() and ingest_benefits() with full test coverage"
```

---

## Done

Backend core is complete: DB models, storage interface, matching engine, and ingest logic
are all tested and working. The FastAPI API layer (Plan 2) imports these modules and wires
them to HTTP routes.

**Next:** `docs/superpowers/plans/2026-05-15-api-layer.md` — FastAPI routes, automation
subprocess runner, and the `data/state.json` refresh state tracker.
