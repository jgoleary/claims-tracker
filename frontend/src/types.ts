export interface AlertOut {
  flag: string
  severity: 'red' | 'yellow' | 'info'
  details: Record<string, unknown>
}

export interface SubmissionResponse {
  id: string
  member_name: string
  provider_name: string
  service_date: string
  amount_billed: number
  expected_reimbursement: number
  network_treatment: 'in_network_exception' | 'out_of_network'
  submitted_date: string | null
  submission_method: 'portal' | 'email'
  pdf_path: string | null
  notes: string | null
  created_at: string
  updated_at: string
  anthem_claim_number: string | null
  anthem_claim_status: 'Pending' | 'Approved' | 'Denied' | null
  anthem_plan_paid: number | null
  flags: AlertOut[]
}

export interface SubmissionCreate {
  member_name: string
  provider_name: string
  service_date: string
  amount_billed: number
  expected_reimbursement: number
  network_treatment: 'in_network_exception' | 'out_of_network'
  submitted_date?: string
  submission_method: 'portal' | 'email'
  notes?: string
}

export interface AnthemClaimResponse {
  claim_number: string
  claim_type: string
  patient_name: string
  service_date: string
  received_date: string | null
  processed_date: string | null
  status: 'Pending' | 'Approved' | 'Denied'
  provider_name: string
  billed: number
  plan_discount: number
  allowed: number
  plan_paid: number
  additional_savings: number
  deductible: number
  coinsurance: number
  copay: number
  not_covered: number
  your_cost: number
  first_seen_at: string
  last_seen_at: string
  is_matched: boolean
}

export interface MatchSuggestion {
  submission: SubmissionResponse
  candidates: AnthemClaimResponse[]
}

export interface IngestSummary {
  new: number
  updated: number
  auto_matched: number
  suggestions: number
}

export interface DashboardCounts {
  missing: number
  stale_pending: number
  denied: number
  underpaid: number
  overpaid: number
  unsubmitted: number
  vanished: number
}

export interface DashboardAlert {
  submission_id: string
  flag: string
  severity: string
  details: Record<string, unknown>
}

export interface DashboardResponse {
  counts: DashboardCounts
  alerts: DashboardAlert[]
}

export interface PlanConfig {
  in_network_coinsurance_pct: number
  out_of_network_coinsurance_pct: number
}

export interface BenefitsSnapshotOut {
  deductible_limit: number
  deductible_spent: number
  oop_limit: number
  oop_spent: number
}

export interface CsvRollup {
  deductible_sum: number
  coinsurance_sum: number
  total_sum: number
}

export interface NetworkTotals {
  benefits: BenefitsSnapshotOut | null
  csv_rollup: CsvRollup
  deductible_diff: number
  oop_diff: number
  has_drift: boolean
}

export interface TotalsResponse {
  in_network: NetworkTotals
  out_of_network: NetworkTotals
}

export interface AutomationStatus {
  status: 'idle' | 'running' | 'complete' | 'failed'
  last_run_at: string | null
  summary: Record<string, unknown> | null
}

export interface ProviderAliasResponse {
  id: number
  canonical_name: string
  anthem_name: string
  confirmed_at: string
}

export interface ExtractionResult {
  configured: boolean
  error: string | null
  member_name: string | null
  provider_name: string | null
  first_service_date: string | null
  amount_billed_cents: number | null
}
