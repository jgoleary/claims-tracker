import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import RedactedName from '../components/RedactedName'
import { formatCents, formatDate } from '../utils'

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-2 border-b border-gray-50 last:border-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="text-sm font-medium text-gray-900">{value}</span>
    </div>
  )
}

export default function AnthemClaimDetail() {
  const { claimNumber } = useParams<{ claimNumber: string }>()
  const { data: claim, isLoading } = useQuery({
    queryKey: ['anthem-claims', claimNumber],
    queryFn: () => api.anthemClaims.get(claimNumber!),
    enabled: !!claimNumber,
  })

  if (isLoading) return <div className="text-gray-500">Loading…</div>
  if (!claim) return <div className="text-red-600">Claim not found</div>

  const statusColor = claim.status === 'Approved'
    ? 'bg-green-100 text-green-700'
    : claim.status === 'Denied'
    ? 'bg-red-100 text-red-700'
    : 'bg-amber-100 text-amber-700'

  return (
    <div className="max-w-2xl">
      <div className="mb-6">
        <Link to="/anthem-claims" className="text-sm text-blue-600 hover:underline">← Anthem Claims</Link>
      </div>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{claim.provider_name}</h1>
          <p className="text-sm text-gray-500 mt-1 font-mono">{claim.claim_number}</p>
        </div>
        <span className={`text-sm font-medium px-3 py-1 rounded-full ${statusColor}`}>{claim.status}</span>
      </div>

      <div className="grid gap-4">
        <div className="bg-white border rounded-lg p-4 shadow-sm">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Claim Info</h2>
          <Row label="Claim Type" value={claim.claim_type} />
          <Row label="Patient" value={<RedactedName value={claim.patient_name} />} />
          <Row label="Service Date" value={formatDate(claim.service_date)} />
          <Row label="Received Date" value={formatDate(claim.received_date)} />
          <Row label="Processed Date" value={formatDate(claim.processed_date)} />
          <Row label="Matched" value={claim.is_matched ? <span className="text-green-600">Yes</span> : <span className="text-gray-400">No</span>} />
        </div>

        <div className="bg-white border rounded-lg p-4 shadow-sm">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Financials</h2>
          <Row label="Billed" value={formatCents(claim.billed)} />
          <Row label="Plan Discount" value={formatCents(claim.plan_discount)} />
          <Row label="Allowed" value={formatCents(claim.allowed)} />
          <Row label="Plan Paid" value={formatCents(claim.plan_paid)} />
          <Row label="Additional Savings" value={formatCents(claim.additional_savings)} />
          <Row label="Deductible" value={formatCents(claim.deductible)} />
          <Row label="Coinsurance" value={formatCents(claim.coinsurance)} />
          <Row label="Copay" value={formatCents(claim.copay)} />
          <Row label="Not Covered" value={formatCents(claim.not_covered)} />
          <Row label="Your Cost" value={<span className="font-bold">{formatCents(claim.your_cost)}</span>} />
        </div>
      </div>
    </div>
  )
}
