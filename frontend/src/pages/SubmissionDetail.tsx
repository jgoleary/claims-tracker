import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import AlertBadge from '../components/Alert'
import { formatCents, formatDate } from '../utils'

export default function SubmissionDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [notes, setNotes] = useState('')

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
          <button onClick={() => { if (window.confirm('Delete this submission?')) deleteMutation.mutate() }}
            className="px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700">Delete</button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-6">
        <div className="bg-white border rounded-lg p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">My Submission</h2>
          <dl className="space-y-3 text-sm">
            {([['Member', sub.member_name], ['Provider', sub.provider_name], ['Service Date', formatDate(sub.service_date)], ['Submitted', formatDate(sub.submitted_date)], ['Method', sub.submission_method], ['Billed', formatCents(sub.amount_billed)], ['Expected', formatCents(sub.expected_reimbursement)], ['Network', sub.network_treatment === 'in_network_exception' ? 'In-Network Exception' : 'Out-of-Network']] as [string, string][]).map(([label, value]) => (
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
                  <dd className={`font-medium ${label === 'Status' && claim.status === 'Denied' ? 'text-red-600' : label === 'Status' && claim.status === 'Approved' ? 'text-green-600' : 'text-gray-900'}`}>{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </div>
  )
}
