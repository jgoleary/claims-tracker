import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'

export const ANTHEM_URL = 'https://membersecure.anthem.com/member/claims/submission-questionnaire'

/**
 * Starts the Anthem claim-filing automation for a submission and reports on it.
 *
 * The script drives Anthem's wizard only as far as the upload step, so the copy
 * here is the sole warning that the user still has to finish the job in the
 * browser window — there is no notification or on-page banner behind it.
 */
export default function ClaimFilingPanel({ submissionId }: { submissionId: string }) {
  const qc = useQueryClient()
  const [started, setStarted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useMutation({
    mutationFn: () => api.claimFiling.run(submissionId),
    onSuccess: (r) => {
      if (r.detail?.toLowerCase().includes('already running')) {
        setBusy(true)
        return
      }
      setStarted(true)
      qc.invalidateQueries({ queryKey: ['claim-filing-status'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  // Kick the run off as soon as the panel mounts.
  useEffect(() => {
    run.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { data: status } = useQuery({
    queryKey: ['claim-filing-status'],
    queryFn: api.claimFiling.status,
    enabled: started,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 3_000 : false),
  })

  const summary = status?.summary as Record<string, string> | null | undefined
  const terminal = status?.status === 'complete' || status?.status === 'failed'

  if (busy) {
    return (
      <div className="p-3 bg-amber-50 border border-amber-200 rounded text-sm text-amber-800">
        Another automation is running, so Anthem's wizard wasn't started. Your submission is
        saved — use <span className="font-medium">File with Anthem</span> on its row once the
        other run finishes, or{' '}
        <a href={ANTHEM_URL} target="_blank" rel="noreferrer" className="underline">
          file it manually
        </a>
        .
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
        Couldn't start the Anthem wizard: {error}. Your submission is saved —{' '}
        <a href={ANTHEM_URL} target="_blank" rel="noreferrer" className="underline">
          file it manually
        </a>
        .
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="p-3 bg-blue-50 border border-blue-200 rounded text-sm text-blue-900">
        <p>
          A browser window is opening. It signs in to Anthem, picks the patient, uploads your
          PDF and waits for Anthem to process it — then stops at{' '}
          <span className="font-medium">Step 3 of 5</span>.
        </p>
        <p className="mt-2 font-medium">
          You must finish the remaining steps and click Submit in that window. Nothing is
          filed with Anthem until you do.
        </p>
        <p className="mt-2 text-blue-800">
          The window closes on its own after 15 minutes — close it yourself when you're done.
        </p>
      </div>

      <div className="text-sm text-gray-700">
        Status:{' '}
        <span
          className={`font-medium ${
            status?.status === 'complete'
              ? 'text-green-600'
              : status?.status === 'failed'
                ? 'text-red-600'
                : status?.status === 'running'
                  ? 'text-blue-600'
                  : 'text-gray-600'
          }`}
        >
          {status?.status ?? 'starting'}
        </span>
      </div>

      {summary && terminal && (
        <div
          className={`rounded p-3 text-xs font-mono whitespace-pre-wrap ${
            status?.status === 'failed' ? 'bg-red-50 text-red-800' : 'bg-gray-50 text-gray-700'
          }`}
        >
          {summary.stdout || ''}
          {summary.stderr ? `\n[stderr]\n${summary.stderr}` : ''}
          {summary.error || ''}
        </div>
      )}
    </div>
  )
}
