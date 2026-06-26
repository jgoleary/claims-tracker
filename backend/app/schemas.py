from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


# ── Submissions ──────────────────────────────────────────────────────────────

class SubmissionCreate(BaseModel):
    member_name: str
    provider_name: str
    service_date: date
    amount_billed: int
    expected_reimbursement: int
    network_treatment: Literal["in_network_exception", "out_of_network"]
    submitted_date: Optional[date] = None
    submission_method: Literal["portal", "email"]
    notes: Optional[str] = None


class SubmissionUpdate(BaseModel):
    member_name: Optional[str] = None
    provider_name: Optional[str] = None
    service_date: Optional[date] = None
    amount_billed: Optional[int] = None
    expected_reimbursement: Optional[int] = None
    network_treatment: Optional[Literal["in_network_exception", "out_of_network"]] = None
    submitted_date: Optional[date] = None
    submission_method: Optional[Literal["portal", "email"]] = None
    notes: Optional[str] = None


class AlertOut(BaseModel):
    flag: str
    severity: str
    details: dict[str, Any] = {}


class SubmissionResponse(BaseModel):
    id: str
    member_name: str
    provider_name: str
    service_date: date
    amount_billed: int
    expected_reimbursement: int
    network_treatment: str
    submitted_date: Optional[date]
    submission_method: str
    pdf_path: Optional[str]
    notes: Optional[str]
    escalated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    anthem_claim_number: Optional[str] = None
    anthem_claim_status: Optional[str] = None
    anthem_plan_paid: Optional[int] = None
    flags: list[AlertOut] = []


class ExtractionResult(BaseModel):
    configured: bool
    error: Optional[str] = None
    member_name: Optional[str] = None
    provider_name: Optional[str] = None
    first_service_date: Optional[date] = None
    amount_billed_cents: Optional[int] = None


class AnthropicKeyStatus(BaseModel):
    configured: bool


# ── Anthem Claims ────────────────────────────────────────────────────────────

class AnthemClaimResponse(BaseModel):
    claim_number: str
    claim_type: str
    patient_name: str
    service_date: date
    received_date: Optional[date]
    processed_date: Optional[date]
    status: str
    provider_name: str
    billed: int
    plan_discount: int
    allowed: int
    plan_paid: int
    additional_savings: int
    deductible: int
    coinsurance: int
    copay: int
    not_covered: int
    your_cost: int
    first_seen_at: datetime
    last_seen_at: datetime
    is_matched: bool = False


# ── Matches ──────────────────────────────────────────────────────────────────

class MatchCreate(BaseModel):
    submission_id: str
    anthem_claim_number: str
    match_type: Literal["auto", "confirmed", "manual"]


class MatchSuggestion(BaseModel):
    submission: SubmissionResponse
    candidates: list[AnthemClaimResponse]


# ── Ingest ───────────────────────────────────────────────────────────────────

class IngestSummary(BaseModel):
    new: int
    updated: int
    auto_matched: int
    suggestions: int


class NetworkData(BaseModel):
    deductible_limit: str
    deductible_spent: str
    oop_limit: str
    oop_spent: str


class BenefitsIngest(BaseModel):
    in_network: NetworkData
    out_of_network: NetworkData


# ── Dashboard ────────────────────────────────────────────────────────────────

class DashboardCounts(BaseModel):
    missing: int = 0
    stale_pending: int = 0
    denied: int = 0
    underpaid: int = 0
    overpaid: int = 0
    unsubmitted: int = 0
    vanished: int = 0


class DashboardAlert(BaseModel):
    submission_id: str
    flag: str
    severity: str
    details: dict[str, Any] = {}


class DashboardResponse(BaseModel):
    counts: DashboardCounts
    alerts: list[DashboardAlert]


# ── Totals ───────────────────────────────────────────────────────────────────

class BenefitsSnapshotOut(BaseModel):
    deductible_limit: int
    deductible_spent: int
    oop_limit: int
    oop_spent: int


class CsvRollup(BaseModel):
    deductible_sum: int
    coinsurance_sum: int
    total_sum: int


class NetworkTotals(BaseModel):
    benefits: Optional[BenefitsSnapshotOut]
    csv_rollup: CsvRollup
    deductible_diff: int
    oop_diff: int
    has_drift: bool


class TotalsResponse(BaseModel):
    in_network: NetworkTotals
    out_of_network: NetworkTotals


# ── Plan Config ──────────────────────────────────────────────────────────────

class PlanConfigResponse(BaseModel):
    in_network_coinsurance_pct: int
    out_of_network_coinsurance_pct: int


class PlanConfigUpdate(BaseModel):
    in_network_coinsurance_pct: int
    out_of_network_coinsurance_pct: int


# ── Automation ───────────────────────────────────────────────────────────────

class AutomationStatus(BaseModel):
    status: Literal["idle", "running", "complete", "failed"]
    last_run_at: Optional[datetime]
    summary: Optional[dict[str, Any]]


# ── Escalation (Included Health) ─────────────────────────────────────────────

class EscalationDraft(BaseModel):
    message: str              # ready-to-send, built from a fixed per-flag template


class EscalationRun(BaseModel):
    message: str


class EscalationStatus(BaseModel):
    status: Literal["idle", "running", "complete", "failed"]
    submission_id: Optional[str] = None
    last_run_at: Optional[datetime]
    summary: Optional[dict[str, Any]]


# ── Providers ────────────────────────────────────────────────────────────────

class ProviderAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    canonical_name: str
    anthem_name: str
    confirmed_at: datetime
