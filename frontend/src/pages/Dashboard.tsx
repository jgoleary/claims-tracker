import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import AlertBadge from '../components/Alert'


export default function Dashboard() {
  const qc = useQueryClient()
  const [activeFlag, setActiveFlag] = useState<string | null>(null)
  const [automationMsg, setAutomationMsg] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard.get,
  })

  const { data: automationStatus } = useQuery({
    queryKey: ['automation-status'],
    queryFn: api.automation.status,
    refetchInterval: (q) => q.state.data?.status === 'running' ? 3_000 : false,
  })

  const runMutation = useMutation({
    mutationFn: api.automation.run,
    onSuccess: (res) => {
      setAutomationMsg(res.detail)
      qc.invalidateQueries({ queryKey: ['automation-status'] })
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['dashboard'] })
        qc.invalidateQueries({ queryKey: ['submissions'] })
      }, 5_000)
    },
  })

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-600">Error loading dashboard</div>
  if (!data) return null

  const counts = data.counts
  const countItems = [
    { flag: 'MISSING', label: 'Missing', count: counts.missing, color: 'bg-red-100 text-red-700 border-red-200' },
    { flag: 'DENIED', label: 'Denied', count: counts.denied, color: 'bg-red-100 text-red-700 border-red-200' },
    { flag: 'STALE_PENDING', label: 'Stale Pending', count: counts.stale_pending, color: 'bg-amber-100 text-amber-700 border-amber-200' },
    { flag: 'UNDERPAID', label: 'Underpaid', count: counts.underpaid, color: 'bg-amber-100 text-amber-700 border-amber-200' },
  ]

  const visibleAlerts = activeFlag ? data.alerts.filter((a) => a.flag === activeFlag) : data.alerts
  const isRunning = automationStatus?.status === 'running'

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <div className="flex items-center gap-3">
          {automationMsg && <span className="text-sm text-gray-500">{automationMsg}</span>}
          {automationStatus?.status === 'complete' && <span className="text-sm text-green-600">Last refresh complete</span>}
          <button
            onClick={() => runMutation.mutate()}
            disabled={isRunning || runMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRunning ? 'Refreshing...' : 'Refresh Data'}
          </button>
        </div>
      </div>

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

      {visibleAlerts.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          {activeFlag ? `No ${activeFlag} alerts` : 'No alerts — everything looks good'}
        </div>
      ) : (
        <div className="space-y-2">
          {visibleAlerts.map((alert, i) => (
            <div key={i} className="flex items-center gap-4 bg-white border rounded-lg px-4 py-3 shadow-sm">
              <AlertBadge flag={alert.flag} severity={alert.severity} />
              <span className="flex-1 text-sm text-gray-700">{alert.submission_id.slice(0, 8)}…</span>
              <span className="text-xs text-gray-400">
                {Object.entries(alert.details).map(([k, v]) => `${k}: ${v}`).join(' · ')}
              </span>
              <Link to={`/submissions/${alert.submission_id}`} className="text-xs text-blue-600 hover:underline">
                View →
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
