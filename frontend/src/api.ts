import type {
  AnthemClaimResponse, AnthropicKeyStatus, AutomationStatus, DashboardResponse,
  ExtractionResult, IngestSummary, MatchSuggestion, PlanConfig,
  ProviderAliasResponse, SubmissionCreate, SubmissionResponse, TotalsResponse,
} from './types'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, init)
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`${resp.status}: ${text}`)
  }
  if (resp.status === 204) return undefined as T
  return resp.json()
}

export const api = {
  submissions: {
    list: (params?: Record<string, string>) => {
      const qs = params ? '?' + new URLSearchParams(params) : ''
      return req<SubmissionResponse[]>(`/submissions${qs}`)
    },
    get: (id: string) => req<SubmissionResponse>(`/submissions/${id}`),
    create: (body: SubmissionCreate) =>
      req<SubmissionResponse>('/submissions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    update: (id: string, body: Partial<SubmissionCreate>) =>
      req<SubmissionResponse>(`/submissions/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    delete: (id: string) => req<void>(`/submissions/${id}`, { method: 'DELETE' }),
    uploadPdf: (id: string, file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return req<void>(`/submissions/${id}/pdf`, { method: 'POST', body: fd })
    },
    pdfUrl: (id: string) => `/api/submissions/${id}/pdf`,
    extract: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return req<ExtractionResult>('/submissions/extract', { method: 'POST', body: fd })
    },
  },
  anthemClaims: {
    list: (params?: Record<string, string>) => {
      const qs = params ? '?' + new URLSearchParams(params) : ''
      return req<AnthemClaimResponse[]>(`/anthem-claims${qs}`)
    },
    get: (claimNumber: string) => req<AnthemClaimResponse>(`/anthem-claims/${claimNumber}`),
  },
  matches: {
    suggestions: () => req<MatchSuggestion[]>('/matches/suggestions'),
    create: (submission_id: string, anthem_claim_number: string, match_type: string) =>
      req<unknown>('/matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ submission_id, anthem_claim_number, match_type }),
      }),
    delete: (submissionId: string) =>
      req<void>(`/matches/${submissionId}`, { method: 'DELETE' }),
  },
  ingest: {
    uploadCsv: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return req<IngestSummary>('/ingest/claims-csv', { method: 'POST', body: fd })
    },
  },
  dashboard: {
    get: (year?: number) => {
      const qs = year ? `?year=${year}` : ''
      return req<DashboardResponse>(`/dashboard${qs}`)
    },
  },
  totals: {
    get: (year?: number) => {
      const qs = year ? `?year=${year}` : ''
      return req<TotalsResponse>(`/totals${qs}`)
    },
  },
  automation: {
    status: () => req<AutomationStatus>('/automation/status'),
    run: () =>
      req<{ detail: string }>('/automation/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }),
  },
  providers: {
    aliases: () => req<ProviderAliasResponse[]>('/providers/aliases'),
    deleteAlias: (id: number) => req<void>(`/providers/aliases/${id}`, { method: 'DELETE' }),
  },
  planConfig: {
    get: () => req<PlanConfig>('/settings/plan-config'),
    update: (body: PlanConfig) =>
      req<PlanConfig>('/settings/plan-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
  },
  settings: {
    anthropicKeyStatus: () => req<AnthropicKeyStatus>('/settings/anthropic-key'),
  },
}
