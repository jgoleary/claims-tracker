import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { AnthemClaimResponse } from '../types'
import { formatCents, formatDate } from '../utils'

function ClaimCard({ claim }: { claim: AnthemClaimResponse }) {
  return (
    <div className="bg-gray-50 border rounded p-3 text-sm space-y-1">
      <div className="font-medium">{claim.provider_name}</div>
      <div className="text-gray-500">{claim.claim_number} · {formatDate(claim.service_date)}</div>
      <div className="flex gap-4 text-xs text-gray-600">
        <span>Billed: {formatCents(claim.billed)}</span>
        <span>Status: <span className={claim.status === 'Denied' ? 'text-red-600 font-medium' : 'text-gray-700'}>{claim.status}</span></span>
      </div>
    </div>
  )
}

export default function Matches() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['suggestions'], queryFn: api.matches.suggestions })
  const confirmMutation = useMutation({
    mutationFn: ({ submissionId, claimNumber }: { submissionId: string; claimNumber: string }) =>
      api.matches.create(submissionId, claimNumber, 'confirmed'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['suggestions'] })
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  if (isLoading) return <div className="text-gray-500">Loading…</div>
  const suggestions = data ?? []
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Match Review</h1>
      {suggestions.length === 0 ? (
        <div className="text-center py-12 text-gray-400">No pending matches to review</div>
      ) : (
        <div className="space-y-6">
          {suggestions.map((s) => (
            <div key={s.submission.id} className="bg-white border rounded-lg shadow-sm overflow-hidden">
              <div className="grid grid-cols-2 divide-x">
                <div className="p-5">
                  <div className="text-xs font-semibold text-gray-400 uppercase mb-3">My Submission</div>
                  <div className="text-sm space-y-1">
                    <div className="font-medium text-gray-900">{s.submission.provider_name}</div>
                    <div className="text-gray-500">{s.submission.member_name} · {formatDate(s.submission.service_date)}</div>
                    <div className="text-gray-600">Billed: {formatCents(s.submission.amount_billed)}</div>
                  </div>
                </div>
                <div className="p-5">
                  <div className="text-xs font-semibold text-gray-400 uppercase mb-3">
                    {s.candidates.length === 1 ? 'Anthem Claim' : `${s.candidates.length} Candidates`}
                  </div>
                  <div className="space-y-2">
                    {s.candidates.map((c) => (
                      <div key={c.claim_number}>
                        <ClaimCard claim={c} />
                        <button
                          onClick={() => confirmMutation.mutate({ submissionId: s.submission.id, claimNumber: c.claim_number })}
                          disabled={confirmMutation.isPending}
                          className="mt-1.5 w-full py-1.5 bg-green-600 text-white rounded text-xs font-medium hover:bg-green-700 disabled:opacity-50"
                        >Confirm Match</button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
