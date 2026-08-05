import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { SubmissionResponse } from '../types'
import Modal from './Modal'
import ClaimFilingPanel from './ClaimFilingPanel'
import { formatDate } from '../utils'

/** Row-action entry point for the Anthem wizard: retry after a failed or
 *  refused run, or file a submission that was saved earlier. */
export default function FileWithAnthemModal({ submission, onClose }: {
  submission: SubmissionResponse
  onClose: () => void
}) {
  const qc = useQueryClient()

  const confirmMutation = useMutation({
    mutationFn: () =>
      api.submissions.update(submission.id, {
        submitted_date: new Date().toISOString().slice(0, 10),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      onClose()
    },
  })

  return (
    <Modal title="File with Anthem" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-gray-500">
          {submission.provider_name} · service {formatDate(submission.service_date)}
        </p>

        <ClaimFilingPanel submissionId={submission.id} />

        <div className="flex justify-end gap-3 pt-1">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
            Close
          </button>
          <button
            onClick={() => confirmMutation.mutate()}
            disabled={confirmMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {confirmMutation.isPending ? 'Saving…' : "I've submitted to Anthem"}
          </button>
        </div>
      </div>
    </Modal>
  )
}
