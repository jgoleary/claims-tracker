import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import RedactedName from '../components/RedactedName'
import { formatCents, formatDate, maskName } from '../utils'
import { useYear } from '../context/YearContext'
import { useRedact } from '../context/RedactContext'

export default function AnthemClaims() {
  const { year } = useYear()
  const { redact } = useRedact()
  const [filterMatched, setFilterMatched] = useState('all')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterPatient, setFilterPatient] = useState('')
  const params: Record<string, string> = { year: String(year) }
  if (filterMatched !== 'all') params.matched = filterMatched
  if (filterStatus) params.status = filterStatus

  const { data, isLoading } = useQuery({
    queryKey: ['anthem-claims', params],
    queryFn: () => api.anthemClaims.list(params),
  })

  const patients = [...new Set((data ?? []).map((c) => c.patient_name).filter(Boolean))].sort(
    (a, b) => a.localeCompare(b)
  )

  const claims = [...(data ?? [])]
    .filter((c) => !filterPatient || c.patient_name === filterPatient)
    .sort((a, b) => (b.service_date ?? '').localeCompare(a.service_date ?? ''))
  const totalDeductible = claims.reduce((s, c) => s + c.deductible, 0)
  const totalCoinsurance = claims.reduce((s, c) => s + c.coinsurance, 0)
  const totalYourCost = claims.reduce((s, c) => s + c.your_cost, 0)

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Anthem Claims</h1>
      <div className="flex gap-3 mb-4">
        <select value={filterMatched} onChange={(e) => setFilterMatched(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="all">All</option>
          <option value="true">Matched</option>
          <option value="false">Unmatched</option>
        </select>
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">All Statuses</option>
          <option value="Pending">Pending</option>
          <option value="Approved">Approved</option>
          <option value="Denied">Denied</option>
        </select>
        <select value={filterPatient} onChange={(e) => setFilterPatient(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">All Patients</option>
          {patients.map((p) => (
            <option key={p} value={p}>{maskName(p, redact)}</option>
          ))}
        </select>
      </div>
      {isLoading ? <div className="text-gray-500">Loading…</div> : (
        <div className="bg-white border rounded-lg overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                {['Patient', 'Provider', 'Service Date', 'Status', 'Billed', 'Plan Paid', 'Deductible', 'Coinsurance', 'Your Cost', 'Matched'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {claims.map((c) => (
                <tr key={c.claim_number} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link to={`/anthem-claims/${encodeURIComponent(c.claim_number)}`} className="font-medium text-blue-600 hover:underline"><RedactedName value={c.patient_name} /></Link>
                  </td>
                  <td className="px-4 py-3 text-gray-700">{c.provider_name}</td>
                  <td className="px-4 py-3 text-gray-500">{formatDate(c.service_date)}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${c.status === 'Approved' ? 'bg-green-100 text-green-700' : c.status === 'Denied' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{c.status}</span>
                  </td>
                  <td className="px-4 py-3">{formatCents(c.billed)}</td>
                  <td className="px-4 py-3">{formatCents(c.plan_paid)}</td>
                  <td className="px-4 py-3">{formatCents(c.deductible)}</td>
                  <td className="px-4 py-3">{formatCents(c.coinsurance)}</td>
                  <td className="px-4 py-3">{formatCents(c.your_cost)}</td>
                  <td className="px-4 py-3 text-center"><span className={c.is_matched ? 'text-green-600' : 'text-gray-300'}>✓</span></td>
                </tr>
              ))}
              {claims.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-8 text-center text-gray-400">No claims imported yet</td></tr>
              )}
            </tbody>
            {claims.length > 0 && (
              <tfoot className="bg-gray-50 border-t-2 border-gray-200">
                <tr>
                  <td colSpan={6} className="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Totals ({claims.length})</td>
                  <td className="px-4 py-3 font-semibold">{formatCents(totalDeductible)}</td>
                  <td className="px-4 py-3 font-semibold">{formatCents(totalCoinsurance)}</td>
                  <td className="px-4 py-3 font-semibold">{formatCents(totalYourCost)}</td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  )
}
