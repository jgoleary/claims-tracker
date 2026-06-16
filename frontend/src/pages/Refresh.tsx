import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { IngestSummary } from '../types'
import { formatDate } from '../utils'

export default function Refresh() {
  const qc = useQueryClient()
  const [csvResult, setCsvResult] = useState<IngestSummary | null>(null)
  const [csvError, setCsvError] = useState<string | null>(null)

  const { data: status } = useQuery({
    queryKey: ['automation-status'],
    queryFn: api.automation.status,
    refetchInterval: (q) => q.state.data?.status === 'running' ? 3_000 : 30_000,
  })

  const runMutation = useMutation({
    mutationFn: () => api.automation.run(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['automation-status'] })
    },
  })

  const csvMutation = useMutation({
    mutationFn: (file: File) => api.ingest.uploadCsv(file),
    onSuccess: (result) => {
      setCsvResult(result)
      setCsvError(null)
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['anthem-claims'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (e: Error) => setCsvError(e.message),
  })

  const isRunning = status?.status === 'running'

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Refresh Data</h1>
      <div className="bg-white border rounded-lg p-6 shadow-sm mb-6">
        <h2 className="font-semibold text-gray-900 mb-1">Run Automation</h2>
        <p className="text-sm text-gray-500 mb-4">Launches the Playwright script using the Anthem credentials stored in the macOS Keychain. Chromium will open — complete MFA if prompted. To set or change credentials, run <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">deploy/store_credentials.py</code>.</p>
        <div className="flex items-center gap-4">
          <button
            onClick={() => runMutation.mutate()}
            disabled={isRunning || runMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRunning ? 'Running…' : 'Refresh Now'}
          </button>
          {status && (
            <span className="text-sm text-gray-500">
              Status: <span className={`font-medium ${status.status === 'complete' ? 'text-green-600' : status.status === 'failed' ? 'text-red-600' : status.status === 'running' ? 'text-blue-600' : 'text-gray-600'}`}>{status.status}</span>
              {status.last_run_at && ` · ${formatDate(status.last_run_at)}`}
            </span>
          )}
        </div>
        {status?.summary && (status.status === 'complete' || status.status === 'failed') && (
          <div className={`mt-4 rounded p-3 text-xs font-mono whitespace-pre-wrap ${status.status === 'failed' ? 'bg-red-50 text-red-800' : 'bg-gray-50 text-gray-700'}`}>
            {(status.summary as Record<string, string>).stdout || ''}
            {(status.summary as Record<string, string>).stderr ? `\n[stderr]\n${(status.summary as Record<string, string>).stderr}` : ''}
            {(status.summary as Record<string, string>).error || ''}
          </div>
        )}
      </div>
      <div className="bg-white border rounded-lg p-6 shadow-sm">
        <h2 className="font-semibold text-gray-900 mb-1">Manual CSV Upload</h2>
        <p className="text-sm text-gray-500 mb-4">Export the CSV from Anthem manually and upload it here.</p>
        <input type="file" accept=".csv"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) csvMutation.mutate(f) }}
          className="text-sm text-gray-600" />
        {csvMutation.isPending && <div className="mt-2 text-sm text-blue-600">Uploading…</div>}
        {csvResult && (
          <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded text-sm text-green-800">
            Done: {csvResult.new} new, {csvResult.updated} updated, {csvResult.auto_matched} auto-matched, {csvResult.suggestions} suggestions
          </div>
        )}
        {csvError && <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{csvError}</div>}
      </div>
    </div>
  )
}
