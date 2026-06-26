import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { SubmissionResponse } from '../types'
import Modal from './Modal'
import { formatDate } from '../utils'

export default function EscalationModal({ submission, onClose }: {
  submission: SubmissionResponse
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [message, setMessage] = useState('')
  const [started, setStarted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const draft = useMutation({
    mutationFn: () => api.escalations.draft(submission.id),
    onSuccess: (d) => setMessage(d.message),
    onError: (e: Error) => setError(e.message),
  })

  // Generate the draft as soon as the modal opens.
  useEffect(() => {
    draft.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { data: status } = useQuery({
    queryKey: ['escalation-status'],
    queryFn: api.escalations.status,
    enabled: started,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 3_000 : false),
  })

  const run = useMutation({
    mutationFn: () => api.escalations.run(submission.id, message),
    onSuccess: (r) => {
      if (r.detail?.toLowerCase().includes('already running')) {
        setError('Another automation is already running — try again once it finishes.')
        return
      }
      setStarted(true)
      qc.invalidateQueries({ queryKey: ['escalation-status'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  // Once the run finishes, refresh the submissions list so the badge appears.
  const statusValue = status?.status
  useEffect(() => {
    if (started && statusValue && statusValue !== 'running') {
      qc.invalidateQueries({ queryKey: ['submissions'] })
    }
  }, [started, statusValue, qc])

  const summary = status?.summary as Record<string, string> | null | undefined

  return (
    <Modal title="Escalate to Included Health" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-gray-500">
          {submission.provider_name} · service {formatDate(submission.service_date)}
        </p>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
        )}

        {!started ? (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Message</label>
              {draft.isPending ? (
                <div className="text-sm text-blue-600">Generating draft…</div>
              ) : (
                <>
                  <textarea
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    rows={7}
                    className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  {draft.data?.source === 'template' && (
                    <p className="text-xs text-amber-700 mt-1">
                      Generated from a template — add an Anthropic API key for AI-refined wording.
                    </p>
                  )}
                </>
              )}
            </div>
            <div className="flex justify-end gap-3 pt-1">
              <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
              <button
                onClick={() => { setError(null); run.mutate() }}
                disabled={run.isPending || draft.isPending || !message.trim()}
                className="px-4 py-2 bg-amber-600 text-white rounded text-sm font-medium hover:bg-amber-700 disabled:opacity-50"
              >
                {run.isPending ? 'Starting…' : 'Start Escalation'}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="text-sm text-gray-700">
              Status:{' '}
              <span className={`font-medium ${
                status?.status === 'complete' ? 'text-green-600'
                : status?.status === 'failed' ? 'text-red-600'
                : status?.status === 'running' ? 'text-blue-600' : 'text-gray-600'
              }`}>
                {status?.status ?? 'starting'}
              </span>
            </div>
            <p className="text-sm text-gray-500">
              A browser window opened — finish login if asked, review the filled form, and click
              Submit. Close the window when you're done.
            </p>
            {summary && (status?.status === 'complete' || status?.status === 'failed') && (
              <div className={`rounded p-3 text-xs font-mono whitespace-pre-wrap ${status?.status === 'failed' ? 'bg-red-50 text-red-800' : 'bg-gray-50 text-gray-700'}`}>
                {summary.stdout || ''}
                {summary.stderr ? `\n[stderr]\n${summary.stderr}` : ''}
                {summary.error || ''}
              </div>
            )}
            <div className="flex justify-end pt-1">
              <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Close</button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
