import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { BenefitsSnapshotOut, ExtractionResult, SubmissionCreate, SubmissionResponse } from '../types'
import Modal from '../components/Modal'
import EscalationModal from '../components/EscalationModal'
import AlertBadge from '../components/Alert'
import RedactedName from '../components/RedactedName'
import { computeExpected, formatCents, formatDate, normalizeProvider } from '../utils'
import { useYear } from '../context/YearContext'
import { useRedact } from '../context/RedactContext'

const ANTHEM_URL = 'https://membersecure.anthem.com/member/claims/submission-questionnaire'

function RemainingBar({ benefits, label }: { benefits: BenefitsSnapshotOut | null; label: string }) {
  if (!benefits) return null
  const dedRemaining = benefits.deductible_limit - benefits.deductible_spent
  const oopRemaining = benefits.oop_limit - benefits.oop_spent
  return (
    <div className="text-xs text-gray-500">
      <span className="font-medium text-gray-600">{label}:</span>
      {' '}Ded remaining <span className="font-medium text-gray-800">{formatCents(dedRemaining)}</span>
      {' · '}OOP remaining <span className="font-medium text-gray-800">{formatCents(oopRemaining)}</span>
    </div>
  )
}

function SubmissionModal({ onClose, initial, memberNames, providerNames }: {
  onClose: () => void
  initial?: SubmissionResponse
  memberNames: string[]
  providerNames: string[]
}) {
  const qc = useQueryClient()
  const { year } = useYear()
  const { redact } = useRedact()
  const isEdit = !!initial

  const { data: totals } = useQuery({ queryKey: ['totals', year], queryFn: () => api.totals.get(year) })
  const { data: planConfig } = useQuery({ queryKey: ['planConfig'], queryFn: api.planConfig.get })
  const { data: networkDefaults } = useQuery({
    queryKey: ['providerNetworkDefaults'],
    queryFn: api.providers.networkDefaults,
    enabled: !isEdit,
  })
  const [step, setStep] = useState<1 | 2>(1)
  const [createdId, setCreatedId] = useState<string | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [extractNote, setExtractNote] = useState<string | null>(null)
  const [expectedDirty, setExpectedDirty] = useState(false)
  const [networkDirty, setNetworkDirty] = useState(false)

  const [form, setForm] = useState({
    member_name: initial?.member_name ?? '',
    provider_name: initial?.provider_name ?? '',
    service_date: initial?.service_date ?? '',
    amount_billed: initial ? String(initial.amount_billed / 100) : '',
    expected_reimbursement: initial ? String(initial.expected_reimbursement / 100) : '',
    network_treatment: (initial?.network_treatment ?? 'out_of_network') as SubmissionCreate['network_treatment'],
    submitted_date: initial?.submitted_date ?? '',
    submission_method: (initial?.submission_method ?? 'portal') as SubmissionCreate['submission_method'],
    notes: initial?.notes ?? '',
  })
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isEdit || expectedDirty || !totals || !planConfig) return
    const billed = Math.round((parseFloat(form.amount_billed) || 0) * 100)
    if (!billed) return
    const oon = form.network_treatment === 'out_of_network'
    const benefits = oon ? totals.out_of_network.benefits : totals.in_network.benefits
    if (!benefits) return
    const dedRemaining = benefits.deductible_limit - benefits.deductible_spent
    const oopRemaining = benefits.oop_limit - benefits.oop_spent
    const pct = (oon ? planConfig.out_of_network_coinsurance_pct : planConfig.in_network_coinsurance_pct) / 100
    const expected = computeExpected(billed, dedRemaining, oopRemaining, pct)
    setForm((p) => ({ ...p, expected_reimbursement: (expected / 100).toFixed(2) }))
  }, [form.amount_billed, form.network_treatment, totals, planConfig, isEdit, expectedDirty])

  // Default Network to the provider's most recently used value (network is a
  // near-constant property of a provider). Skips edits and any manual override.
  useEffect(() => {
    if (isEdit || networkDirty || !networkDefaults) return
    const last = networkDefaults[normalizeProvider(form.provider_name)]
    if (last && last !== form.network_treatment) {
      setForm((p) => ({ ...p, network_treatment: last as SubmissionCreate['network_treatment'] }))
    }
  }, [form.provider_name, form.network_treatment, networkDefaults, isEdit, networkDirty])

  const mutation = useMutation({
    mutationFn: async () => {
      const dollars = {
        amount_billed: Math.round((parseFloat(form.amount_billed) || 0) * 100),
        expected_reimbursement: Math.round((parseFloat(form.expected_reimbursement) || 0) * 100),
      }
      if (isEdit) {
        return api.submissions.update(initial!.id, { ...form, ...dollars })
      } else {
        const body: SubmissionCreate = {
          member_name: form.member_name,
          provider_name: form.provider_name,
          service_date: form.service_date,
          network_treatment: form.network_treatment,
          submission_method: form.submission_method,
          notes: form.notes,
          ...dollars,
        }
        const sub = await api.submissions.create(body)
        if (pdfFile) await api.submissions.uploadPdf(sub.id, pdfFile)
        return sub
      }
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['providerNetworkDefaults'] })
      if (isEdit) { onClose(); return }
      setCreatedId(result.id)
      window.open(ANTHEM_URL, '_blank')
      setStep(2)
    },
    onError: (e: Error) => setError(e.message),
  })

  const confirmMutation = useMutation({
    mutationFn: () => api.submissions.update(createdId!, { submitted_date: new Date().toISOString().slice(0, 10) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onClose()
    },
  })

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((prev) => ({ ...prev, [k]: e.target.value }))

  if (step === 2) {
    return (
      <Modal title="Submit to Anthem" onClose={onClose}>
        <div className="space-y-4">
          <div className="text-sm text-green-700">{'✓'} Submission saved locally.</div>
          <p className="text-sm text-gray-600">
            Anthem's claim questionnaire was opened in a new tab. Once you've submitted the
            claim there, confirm it below.
          </p>
          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Do it later</button>
            <button onClick={() => confirmMutation.mutate()} disabled={confirmMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {confirmMutation.isPending ? 'Saving…' : "I've submitted to Anthem"}
            </button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title={isEdit ? 'Edit Submission' : 'Add Submission'} onClose={onClose}>
      <div className="space-y-3">
        {error && <div className="text-red-600 text-sm">{error}</div>}
        {(['member_name', 'provider_name'] as const).map((key) => (
          <div key={key}>
            <label className="block text-sm font-medium text-gray-700 mb-1 capitalize">{key.replace(/_/g, ' ')}</label>
            <input
              type="text"
              value={form[key]}
              onChange={set(key)}
              list={key === 'member_name' ? 'member-options' : 'provider-options'}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        ))}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Service Date</label>
            <input type="date" value={form.service_date} onChange={set('service_date')}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          {isEdit && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Submitted Date</label>
              <input type="date" value={form.submitted_date} onChange={set('submitted_date')}
                className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          )}
        </div>
        <datalist id="member-options">
          {!redact && memberNames.map((n) => <option key={n} value={n} />)}
        </datalist>
        <datalist id="provider-options">
          {providerNames.map((n) => <option key={n} value={n} />)}
        </datalist>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Billed ($)</label>
            <input type="number" step="0.01" value={form.amount_billed}
              onChange={(e) => setForm((p) => ({ ...p, amount_billed: e.target.value }))}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Expected ($)</label>
            <input type="number" step="0.01" value={form.expected_reimbursement}
              onChange={(e) => { setExpectedDirty(true); setForm((p) => ({ ...p, expected_reimbursement: e.target.value })) }}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Network</label>
            <select value={form.network_treatment}
              onChange={(e) => { setNetworkDirty(true); setForm((p) => ({ ...p, network_treatment: e.target.value as SubmissionCreate['network_treatment'] })) }}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="out_of_network">Out-of-Network</option>
              <option value="in_network_exception">In-Network Exception</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Method</label>
            <select value={form.submission_method} onChange={set('submission_method')}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="portal">Portal</option>
              <option value="email">Email</option>
            </select>
          </div>
        </div>
        {!isEdit && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">PDF (optional)</label>
            <div className="flex items-center gap-3">
              <input type="file" accept=".pdf" onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)} className="text-sm" />
              <button
                type="button"
                disabled={!pdfFile || extracting}
                onClick={async () => {
                  if (!pdfFile) return
                  setExtracting(true)
                  setExtractNote(null)
                  try {
                    const r: ExtractionResult = await api.submissions.extract(pdfFile)
                    if (!r.configured) { setExtractNote('PDF auto-fill unavailable (no API key configured).'); return }
                    if (r.error) { setExtractNote("Couldn’t read the PDF — please enter fields manually."); return }
                    setForm((p) => ({
                      ...p,
                      member_name: r.member_name ?? p.member_name,
                      provider_name: r.provider_name ?? p.provider_name,
                      service_date: r.first_service_date ?? p.service_date,
                      amount_billed: r.amount_billed_cents != null ? String(r.amount_billed_cents / 100) : p.amount_billed,
                    }))
                  } catch {
                    setExtractNote("Couldn’t read the PDF — please enter fields manually.")
                  } finally {
                    setExtracting(false)
                  }
                }}
                className="px-3 py-1 text-sm border rounded text-blue-700 border-blue-300 hover:bg-blue-50 disabled:opacity-50">
                {extracting ? 'Reading…' : 'Extract from PDF'}
              </button>
            </div>
            {extractNote && <div className="text-xs text-amber-700 mt-1">{extractNote}</div>}
          </div>
        )}
        {totals && (
          <div className="pt-2 pb-1 space-y-1 border-t">
            <RemainingBar benefits={totals.in_network.benefits} label="In-Network" />
            <RemainingBar benefits={totals.out_of_network.benefits} label="Out-of-Network" />
          </div>
        )}
        <div className="flex justify-end gap-3 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
          <button onClick={() => mutation.mutate()} disabled={mutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {mutation.isPending ? 'Saving…' : isEdit ? 'Save Changes' : 'Add Submission'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default function Submissions() {
  const { year } = useYear()
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState<SubmissionResponse | null>(null)
  const [escalating, setEscalating] = useState<SubmissionResponse | null>(null)
  const [filterMember, setFilterMember] = useState('')
  const [filterStatus, setFilterStatus] = useState('all')

  const params: Record<string, string> = { year: String(year) }
  if (filterMember) params.member = filterMember
  if (filterStatus !== 'all') params.status = filterStatus

  const { data, isLoading } = useQuery({
    queryKey: ['submissions', params],
    queryFn: () => api.submissions.list(params),
  })

  const memberNames = [...new Set((data ?? []).map((s) => s.member_name))].sort()
  const providerNames = [...new Set((data ?? []).map((s) => s.provider_name))].sort()

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Submissions</h1>
        <button onClick={() => setShowAdd(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700">
          Add Submission
        </button>
      </div>
      <div className="flex gap-3 mb-4">
        <input placeholder="Filter by member…" value={filterMember} onChange={(e) => setFilterMember(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="all">All</option>
          <option value="matched">Matched</option>
          <option value="unmatched">Unmatched</option>
        </select>
      </div>
      {isLoading ? <div className="text-gray-500">Loading…</div> : (
        <div className="bg-white border rounded-lg overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                {['Member', 'Provider', 'Service Date', 'Billed', 'Expected', 'Submitted', 'Match Status', 'Anthem Status', 'Plan Paid', 'Flags', ''].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(data ?? []).map((sub) => (
                <tr key={sub.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link to={`/submissions/${sub.id}`} className="font-medium text-blue-600 hover:underline"><RedactedName value={sub.member_name} /></Link>
                  </td>
                  <td className="px-4 py-3 text-gray-700">{sub.provider_name}</td>
                  <td className="px-4 py-3 text-gray-500">{formatDate(sub.service_date)}</td>
                  <td className="px-4 py-3">{formatCents(sub.amount_billed)}</td>
                  <td className="px-4 py-3">{formatCents(sub.expected_reimbursement)}</td>
                  <td className="px-4 py-3 text-gray-500">{formatDate(sub.submitted_date)}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${sub.anthem_claim_number ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                      {sub.anthem_claim_number ? 'Matched' : 'Unmatched'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {sub.anthem_claim_status ? (
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                        sub.anthem_claim_status === 'Approved' ? 'bg-green-100 text-green-700'
                        : sub.anthem_claim_status === 'Denied' ? 'bg-red-100 text-red-700'
                        : 'bg-amber-100 text-amber-700'
                      }`}>
                        {sub.anthem_claim_status}
                      </span>
                    ) : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    {sub.anthem_plan_paid != null ? formatCents(sub.anthem_plan_paid) : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1 flex-wrap">
                      {sub.flags.map((f, i) => <AlertBadge key={i} flag={f.flag} severity={f.severity} />)}
                      {sub.escalated_at && (
                        <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-700">Escalated</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-3">
                      <button
                        onClick={() => setEscalating(sub)}
                        className="text-xs text-gray-400 hover:text-amber-600 transition-colors"
                      >
                        Escalate
                      </button>
                      <button
                        onClick={() => setEditing(sub)}
                        className="text-xs text-gray-400 hover:text-blue-600 transition-colors"
                      >
                        Edit
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {(data ?? []).length === 0 && (
                <tr><td colSpan={11} className="px-4 py-8 text-center text-gray-400">No submissions</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {showAdd && (
        <SubmissionModal
          onClose={() => setShowAdd(false)}
          memberNames={memberNames}
          providerNames={providerNames}
        />
      )}
      {editing && (
        <SubmissionModal
          onClose={() => setEditing(null)}
          initial={editing}
          memberNames={memberNames}
          providerNames={providerNames}
        />
      )}
      {escalating && (
        <EscalationModal
          submission={escalating}
          onClose={() => setEscalating(null)}
        />
      )}
    </div>
  )
}
