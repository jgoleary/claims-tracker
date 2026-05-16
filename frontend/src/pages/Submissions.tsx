import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { SubmissionCreate } from '../types'
import Modal from '../components/Modal'
import AlertBadge from '../components/Alert'
import { formatCents, formatDate } from '../utils'

function AddModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<SubmissionCreate>({
    member_name: '', provider_name: '', service_date: '', amount_billed: 0,
    expected_reimbursement: 0, network_treatment: 'out_of_network',
    submitted_date: '', submission_method: 'portal', notes: '',
  })
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: async () => {
      const body = { ...form, amount_billed: Math.round(form.amount_billed * 100), expected_reimbursement: Math.round(form.expected_reimbursement * 100) }
      const sub = await api.submissions.create(body)
      if (pdfFile) await api.submissions.uploadPdf(sub.id, pdfFile)
      return sub
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['submissions'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }); onClose() },
    onError: (e: Error) => setError(e.message),
  })

  const set = (k: keyof SubmissionCreate) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((prev) => ({ ...prev, [k]: e.target.value }))

  return (
    <Modal title="Add Submission" onClose={onClose}>
      <div className="space-y-3">
        {error && <div className="text-red-600 text-sm">{error}</div>}
        {(['member_name', 'provider_name', 'service_date', 'submitted_date'] as (keyof SubmissionCreate)[]).map((key) => (
          <div key={key}>
            <label className="block text-sm font-medium text-gray-700 mb-1 capitalize">{key.replace('_', ' ')}</label>
            <input
              type={key.includes('date') ? 'date' : 'text'}
              value={form[key] as string}
              onChange={set(key)}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        ))}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Billed ($)</label>
            <input type="number" step="0.01" value={form.amount_billed}
              onChange={(e) => setForm((p) => ({ ...p, amount_billed: parseFloat(e.target.value) || 0 }))}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Expected ($)</label>
            <input type="number" step="0.01" value={form.expected_reimbursement}
              onChange={(e) => setForm((p) => ({ ...p, expected_reimbursement: parseFloat(e.target.value) || 0 }))}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Network</label>
            <select value={form.network_treatment} onChange={set('network_treatment')}
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
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">PDF (optional)</label>
          <input type="file" accept=".pdf" onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)} className="text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
          <textarea value={form.notes ?? ''} onChange={set('notes')} rows={2}
            className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div className="flex justify-end gap-3 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
          <button onClick={() => mutation.mutate()} disabled={mutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {mutation.isPending ? 'Saving…' : 'Add Submission'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default function Submissions() {
  const [showAdd, setShowAdd] = useState(false)
  const [filterMember, setFilterMember] = useState('')
  const [filterStatus, setFilterStatus] = useState('all')

  const params: Record<string, string> = {}
  if (filterMember) params.member = filterMember
  if (filterStatus !== 'all') params.status = filterStatus

  const { data, isLoading } = useQuery({
    queryKey: ['submissions', params],
    queryFn: () => api.submissions.list(Object.keys(params).length ? params : undefined),
  })

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
                {['Member', 'Provider', 'Service Date', 'Billed', 'Expected', 'Submitted', 'Status', 'Flags'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(data ?? []).map((sub) => (
                <tr key={sub.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link to={`/submissions/${sub.id}`} className="font-medium text-blue-600 hover:underline">{sub.member_name}</Link>
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
                    <div className="flex gap-1 flex-wrap">
                      {sub.flags.map((f, i) => <AlertBadge key={i} flag={f.flag} severity={f.severity} />)}
                    </div>
                  </td>
                </tr>
              ))}
              {(data ?? []).length === 0 && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No submissions</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {showAdd && <AddModal onClose={() => setShowAdd(false)} />}
    </div>
  )
}
