import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { NetworkTotals } from '../types'
import { formatCents } from '../utils'

function NetworkCard({ label, data }: { label: string; data: NetworkTotals }) {
  const { benefits, csv_rollup, deductible_diff, oop_diff, has_drift } = data
  return (
    <div className={`bg-white border rounded-lg p-6 shadow-sm ${has_drift ? 'border-amber-300' : ''}`}>
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
        {label}
        {has_drift && <span className="ml-2 text-amber-600 text-xs">⚠ Drift detected</span>}
      </h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-gray-400 uppercase">
            <th className="text-left pb-2"></th>
            <th className="text-right pb-2">Benefits Page</th>
            <th className="text-right pb-2">CSV Sum</th>
            <th className="text-right pb-2">Diff</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          <tr>
            <td className="py-2 text-gray-600">Deductible</td>
            <td className="py-2 text-right">{benefits ? formatCents(benefits.deductible_spent) : '—'}</td>
            <td className="py-2 text-right">{formatCents(csv_rollup.deductible_sum)}</td>
            <td className={`py-2 text-right font-medium ${Math.abs(deductible_diff) > 5000 ? 'text-amber-600' : 'text-gray-700'}`}>
              {deductible_diff !== 0 ? formatCents(Math.abs(deductible_diff)) : '—'}
            </td>
          </tr>
          <tr>
            <td className="py-2 text-gray-600">OOP (Ded + Coins)</td>
            <td className="py-2 text-right">{benefits ? formatCents(benefits.oop_spent) : '—'}</td>
            <td className="py-2 text-right">{formatCents(csv_rollup.total_sum)}</td>
            <td className={`py-2 text-right font-medium ${Math.abs(oop_diff) > 5000 ? 'text-amber-600' : 'text-gray-700'}`}>
              {oop_diff !== 0 ? formatCents(Math.abs(oop_diff)) : '—'}
            </td>
          </tr>
        </tbody>
      </table>
      {benefits && (
        <div className="mt-4 pt-4 border-t grid grid-cols-2 gap-2 text-xs text-gray-500">
          <div>Deductible limit: {formatCents(benefits.deductible_limit)}</div>
          <div>OOP limit: {formatCents(benefits.oop_limit)}</div>
        </div>
      )}
    </div>
  )
}

export default function Totals() {
  const { data, isLoading } = useQuery({ queryKey: ['totals'], queryFn: api.totals.get })
  if (isLoading) return <div className="text-gray-500">Loading…</div>
  if (!data) return null
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Totals</h1>
      <div className="grid grid-cols-2 gap-6">
        <NetworkCard label="In-Network" data={data.in_network} />
        <NetworkCard label="Out-of-Network" data={data.out_of_network} />
      </div>
    </div>
  )
}
