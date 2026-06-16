import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import AlertBadge from '../components/Alert'
import { useYear } from '../context/YearContext'

export default function Dashboard() {
  const { year } = useYear()
  const [activeFlag, setActiveFlag] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard', year],
    queryFn: () => api.dashboard.get(year),
  })

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-600">Error loading dashboard</div>
  if (!data) return null

  const counts = data.counts
  const countItems = [
    { flag: 'MISSING', label: 'Missing', count: counts.missing, color: 'bg-red-100 text-red-700 border-red-200' },
    { flag: 'VANISHED', label: 'Vanished', count: counts.vanished, color: 'bg-red-100 text-red-700 border-red-200' },
    { flag: 'DENIED', label: 'Denied', count: counts.denied, color: 'bg-red-100 text-red-700 border-red-200' },
    { flag: 'STALE_PENDING', label: 'Stale Pending', count: counts.stale_pending, color: 'bg-amber-100 text-amber-700 border-amber-200' },
    { flag: 'UNDERPAID', label: 'Underpaid', count: counts.underpaid, color: 'bg-amber-100 text-amber-700 border-amber-200' },
  ]

  // Group alerts by submission so each submission is a single row carrying all
  // its flags. data.alerts arrives severity-sorted, so insertion order keeps the
  // most-severe submissions (and badges within a row) first.
  const bySubmission = new Map<string, typeof data.alerts>()
  for (const a of data.alerts) {
    const list = bySubmission.get(a.submission_id) ?? []
    list.push(a)
    bySubmission.set(a.submission_id, list)
  }
  let rows = [...bySubmission.entries()]
  if (activeFlag) {
    rows = rows.filter(([, alerts]) => alerts.some((a) => a.flag === activeFlag))
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Dashboard</h1>

      <div className="grid grid-cols-4 gap-4 mb-6">
        {countItems.map(({ flag, label, count, color }) => (
          <button
            key={flag}
            onClick={() => setActiveFlag(activeFlag === flag ? null : flag)}
            className={`border rounded-lg p-4 text-left transition-all ${color} ${activeFlag === flag ? 'ring-2 ring-offset-1 ring-current' : 'hover:opacity-80'}`}
          >
            <div className="text-3xl font-bold">{count}</div>
            <div className="text-sm font-medium mt-1">{label}</div>
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          {activeFlag ? `No ${activeFlag} alerts` : 'No alerts — everything looks good'}
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map(([submissionId, alerts]) => (
            <div key={submissionId} className="flex items-center gap-4 bg-white border rounded-lg px-4 py-3 shadow-sm">
              <div className="flex flex-wrap gap-1">
                {alerts.map((a, i) => <AlertBadge key={i} flag={a.flag} severity={a.severity} />)}
              </div>
              <span className="flex-1 text-sm text-gray-700">{submissionId.slice(0, 8)}…</span>
              <span className="text-xs text-gray-400">
                {alerts
                  .flatMap((a) => Object.entries(a.details).map(([k, v]) => `${k}: ${v}`))
                  .join(' · ')}
              </span>
              <Link to={`/submissions/${submissionId}`} className="text-xs text-blue-600 hover:underline">
                View →
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
