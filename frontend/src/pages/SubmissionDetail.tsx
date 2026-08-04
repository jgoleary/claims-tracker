import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import AlertBadge from '../components/Alert'
import Modal from '../components/Modal'
import { formatCents, formatDate, maskName } from '../utils'
import { useRedact } from '../context/RedactContext'
import { useYear } from '../context/YearContext'
import type { SubmissionResponse } from '../types'

export default function SubmissionDetail() {
  const { id } = useParams<{ id: string }>()
  const { redact } = useRedact()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [notes, setNotes] = useState('')
  const [deprecating, setDeprecating] = useState(false)

  const { data: sub, isLoading } = useQuery({
    queryKey: ['submission', id],
    queryFn: () => api.submissions.get(id!),
    enabled: !!id,
  })

  const { data: claim } = useQuery({
    queryKey: ['anthem-claim', sub?.anthem_claim_number],
    queryFn: () => api.anthemClaims.get(sub!.anthem_claim_number!),
    enabled: !!sub?.anthem_claim_number,
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.submissions.delete(id!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['submissions'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }); navigate('/submissions') },
  })

  const unmatchMutation = useMutation({
    mutationFn: () => api.matches.delete(id!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['submission', id] }); qc.invalidateQueries({ queryKey: ['dashboard'] }) },
  })

  const updateMutation = useMutation({
    mutationFn: () => api.submissions.update(id!, { notes }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['submission', id] }); setEditing(false) },
  })

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ['submission', id] })
    qc.invalidateQueries({ queryKey: ['submissions'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }

  const unsupersedeMutation = useMutation({
    mutationFn: () => api.submissions.unsupersede(id!),
    onSuccess: invalidateAll,
  })

  const resolveMutation = useMutation({
    mutationFn: () => api.submissions.resolve(id!),
    onSuccess: invalidateAll,
  })

  const unresolveMutation = useMutation({
    mutationFn: () => api.submissions.unresolve(id!),
    onSuccess: invalidateAll,
  })

  if (isLoading) return <div className="text-gray-500">Loading…</div>
  if (!sub) return <div className="text-red-600">Submission not found</div>

  return (
    <div>
      <div className="flex items-center gap-4 mb-6">
        <Link to="/submissions" className="text-blue-600 text-sm hover:underline">← Back</Link>
        <h1 className="text-2xl font-bold text-gray-900 flex-1">{sub.provider_name} — {formatDate(sub.service_date)}</h1>
        <div className="flex gap-2">
          {sub.anthem_claim_number && (
            <button onClick={() => unmatchMutation.mutate()}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50">Unmatch</button>
          )}
          {!sub.resolved_at && !sub.superseded_by && (
            <>
              <button onClick={() => resolveMutation.mutate()} disabled={resolveMutation.isPending}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50">Resolve</button>
              <button onClick={() => setDeprecating(true)}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50">Deprecate</button>
            </>
          )}
          <button onClick={() => { if (window.confirm('Delete this submission?')) deleteMutation.mutate() }}
            className="px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700">Delete</button>
        </div>
      </div>
      {sub.resolved_at && (
        <div className="mb-6 flex items-center justify-between gap-4 bg-gray-100 border border-gray-200 rounded-lg px-4 py-3 text-sm">
          <div className="text-gray-700">
            Resolved {formatDate(sub.resolved_at)} — no further action needed. It raises no
            alerts, and will reopen automatically if Anthem's data gives it a new flag.
          </div>
          <button onClick={() => unresolveMutation.mutate()} disabled={unresolveMutation.isPending}
            className="shrink-0 px-3 py-1.5 text-sm border border-gray-300 rounded bg-white hover:bg-gray-50 disabled:opacity-50">Undo</button>
        </div>
      )}
      {sub.superseded_by && (
        <div className="mb-6 flex items-center justify-between gap-4 bg-gray-100 border border-gray-200 rounded-lg px-4 py-3 text-sm">
          <div className="text-gray-700">
            Deprecated — superseded by{' '}
            <Link to={`/submissions/${sub.superseded_by.id}`} className="text-blue-600 font-medium hover:underline">
              {sub.superseded_by.provider_name} — {formatDate(sub.superseded_by.submitted_date ?? sub.superseded_by.service_date)}
            </Link>
          </div>
          <button onClick={() => unsupersedeMutation.mutate()}
            className="shrink-0 px-3 py-1.5 text-sm border border-gray-300 rounded bg-white hover:bg-gray-50">Undo</button>
        </div>
      )}
      <div className="grid grid-cols-2 gap-6">
        <div className="bg-white border rounded-lg p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">My Submission</h2>
          <dl className="space-y-3 text-sm">
            {([['Member', maskName(sub.member_name, redact)], ['Provider', sub.provider_name], ['Service Date', formatDate(sub.service_date)], ['Submitted', formatDate(sub.submitted_date)], ['Method', sub.submission_method], ['Billed', formatCents(sub.amount_billed)], ['Expected', formatCents(sub.expected_reimbursement)], ['Network', sub.network_treatment === 'in_network_exception' ? 'In-Network Exception' : 'Out-of-Network']] as [string, string][]).map(([label, value]) => (
              <div key={label} className="flex justify-between">
                <dt className="text-gray-500">{label}</dt>
                <dd className="font-medium text-gray-900">{value}</dd>
              </div>
            ))}
          </dl>
          {sub.flags.length > 0 && (
            <div className="mt-4 pt-4 border-t flex gap-2 flex-wrap">
              {sub.flags.map((f, i) => <AlertBadge key={i} flag={f.flag} severity={f.severity} />)}
            </div>
          )}
          {sub.supersedes && sub.supersedes.length > 0 && (
            <div className="mt-4 pt-4 border-t text-sm">
              <span className="text-gray-500">Supersedes: </span>
              {sub.supersedes.map((s, i) => (
                <span key={s.id}>
                  {i > 0 && ', '}
                  <Link to={`/submissions/${s.id}`} className="text-blue-600 hover:underline">
                    {s.provider_name} — {formatDate(s.submitted_date ?? s.service_date)}
                  </Link>
                </span>
              ))}
            </div>
          )}
          <div className="mt-4 pt-4 border-t">
            {editing ? (
              <div className="space-y-2">
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
                  className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                <div className="flex gap-2">
                  <button onClick={() => updateMutation.mutate()} className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm">Save</button>
                  <button onClick={() => setEditing(false)} className="px-3 py-1.5 text-gray-600 text-sm">Cancel</button>
                </div>
              </div>
            ) : (
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm text-gray-600 flex-1">{sub.notes || <span className="text-gray-400 italic">No notes</span>}</p>
                <button onClick={() => { setNotes(sub.notes ?? ''); setEditing(true) }} className="text-xs text-blue-600 hover:underline shrink-0">Edit</button>
              </div>
            )}
          </div>
          {sub.pdf_path && (
            <div className="mt-4 pt-4 border-t">
              <a href={api.submissions.pdfUrl(sub.id)} target="_blank" rel="noreferrer" className="text-sm text-blue-600 hover:underline">Download PDF →</a>
            </div>
          )}
        </div>
        <div className="bg-white border rounded-lg p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">Anthem Claim</h2>
          {!claim ? (
            <div className="text-gray-400 text-sm py-8 text-center">
              {sub.anthem_claim_number ? 'Loading…' : 'Not matched yet.'}
              {!sub.anthem_claim_number && <div className="mt-2"><Link to="/matches" className="text-blue-600 hover:underline text-sm">Review suggestions →</Link></div>}
            </div>
          ) : (
            <dl className="space-y-3 text-sm">
              {([['Claim #', claim.claim_number], ['Status', claim.status], ['Service Date', formatDate(claim.service_date)], ['Provider (Anthem)', claim.provider_name], ['Billed', formatCents(claim.billed)], ['Plan Paid', formatCents(claim.plan_paid)], ['Deductible', formatCents(claim.deductible)], ['Coinsurance', formatCents(claim.coinsurance)], ['Your Cost', formatCents(claim.your_cost)]] as [string, string][]).map(([label, value]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-gray-500">{label}</dt>
                  <dd className={`font-medium ${label === 'Status' && (claim.status === 'Denied' || claim.status === 'Deleted') ? 'text-red-600' : label === 'Status' && claim.status === 'Approved' ? 'text-green-600' : 'text-gray-900'}`}>{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
      {deprecating && (
        <DeprecateModal submission={sub} onClose={() => setDeprecating(false)} onDone={invalidateAll} />
      )}
    </div>
  )
}

function DeprecateModal({ submission, onClose, onDone }: {
  submission: SubmissionResponse
  onClose: () => void
  onDone: () => void
}) {
  const { year } = useYear()
  const { redact } = useRedact()

  const { data, isLoading } = useQuery({
    queryKey: ['submissions', { member: submission.member_name, year }],
    queryFn: () => api.submissions.list({ member: submission.member_name, year: String(year) }),
  })

  const supersedeMutation = useMutation({
    mutationFn: (successorId: string) => api.submissions.supersede(submission.id, successorId),
    onSuccess: () => { onDone(); onClose() },
  })

  const candidates = (data ?? []).filter((s) => s.id !== submission.id)

  return (
    <Modal title="Deprecate submission" onClose={onClose}>
      <p className="text-sm text-gray-600 mb-4">
        Pick the submission that follows this one up. This submission will be marked deprecated
        and will stop raising alerts.
      </p>
      {isLoading ? (
        <div className="text-gray-500 text-sm">Loading…</div>
      ) : candidates.length === 0 ? (
        <div className="text-gray-400 text-sm">
          No other submissions for {maskName(submission.member_name, redact)} to point to.
        </div>
      ) : (
        <div className="space-y-2">
          {candidates.map((c) => (
            <button
              key={c.id}
              onClick={() => supersedeMutation.mutate(c.id)}
              disabled={supersedeMutation.isPending}
              className="w-full text-left border rounded px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              <div className="font-medium text-gray-900">{c.provider_name}</div>
              <div className="text-gray-500">
                Service {formatDate(c.service_date)} · Submitted {formatDate(c.submitted_date)} · {formatCents(c.amount_billed)}
              </div>
            </button>
          ))}
        </div>
      )}
      {supersedeMutation.isError && (
        <div className="mt-3 text-sm text-red-600">Failed to deprecate. Please try again.</div>
      )}
    </Modal>
  )
}
