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
        String, ForeignKey("anthem_claims.claim_number"), nullable=False, unique=True
    )
    match_type: Mapped[str] = mapped_column(
        SAEnum("auto", "confirmed", "manual", name="match_type"),
        nullable=False,
    )
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

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
