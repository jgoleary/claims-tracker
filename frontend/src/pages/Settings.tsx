import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'

export default function Settings() {
  const qc = useQueryClient()
  const { data: aliases, isLoading } = useQuery({ queryKey: ['aliases'], queryFn: api.providers.aliases })
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.providers.deleteAlias(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['aliases'] }),
  })

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Settings</h1>
      <div className="bg-white border rounded-lg p-6 shadow-sm mb-6">
        <h2 className="font-semibold text-gray-900 mb-1">Provider Aliases</h2>
        <p className="text-sm text-gray-500 mb-4">Learned from confirmed matches. Used for automatic matching.</p>
        {isLoading ? <div className="text-gray-500 text-sm">Loading…</div> : !aliases?.length ? (
          <div className="text-gray-400 text-sm">No aliases yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b">
              <tr className="text-xs text-gray-400 uppercase">
                <th className="text-left pb-2">Your Name</th>
                <th className="text-left pb-2">Anthem Name</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {aliases.map((a) => (
                <tr key={a.id}>
                  <td className="py-2 text-gray-700">{a.canonical_name}</td>
                  <td className="py-2 text-gray-500">{a.anthem_name}</td>
                  <td className="py-2 text-right">
                    <button onClick={() => deleteMutation.mutate(a.id)} className="text-xs text-red-600 hover:underline">Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="bg-white border rounded-lg p-6 shadow-sm">
        <h2 className="font-semibold text-gray-900 mb-1">Alert Thresholds</h2>
        <p className="text-sm text-gray-500 mb-3">Edit <code className="bg-gray-100 px-1 rounded text-xs">backend/app/config.py</code> to change these.</p>
        <dl className="space-y-2 text-sm">
          {[['MISSING after', '30 days'], ['STALE_PENDING after', '30 days'], ['VANISHED', 'gone from latest export'], ['UNDERPAID threshold', '$25 or 10%'], ['Totals drift', '$50']].map(([label, value]) => (
            <div key={label} className="flex justify-between">
              <dt className="text-gray-500">{label}</dt>
              <dd className="font-medium text-gray-900">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
