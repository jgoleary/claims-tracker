import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useRedact } from '../context/RedactContext'

export default function Settings() {
  const qc = useQueryClient()
  const { redact, toggle } = useRedact()
  const { data: aliases, isLoading } = useQuery({ queryKey: ['aliases'], queryFn: api.providers.aliases })
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.providers.deleteAlias(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['aliases'] }),
  })

  const { data: planConfig } = useQuery({ queryKey: ['planConfig'], queryFn: api.planConfig.get })
  const { data: anthropicKey } = useQuery({ queryKey: ['anthropicKey'], queryFn: api.settings.anthropicKeyStatus })
  const [inPct, setInPct] = useState(10)
  const [oonPct, setOonPct] = useState(30)
  const [configDirty, setConfigDirty] = useState(false)

  useEffect(() => {
    if (planConfig) {
      setInPct(planConfig.in_network_coinsurance_pct)
      setOonPct(planConfig.out_of_network_coinsurance_pct)
      setConfigDirty(false)
    }
  }, [planConfig])

  const configMutation = useMutation({
    mutationFn: () => api.planConfig.update({ in_network_coinsurance_pct: inPct, out_of_network_coinsurance_pct: oonPct }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['planConfig'] }); setConfigDirty(false) },
  })

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Settings</h1>
      <div className="bg-white border rounded-lg p-6 shadow-sm mb-6">
        <h2 className="font-semibold text-gray-900 mb-1">Privacy</h2>
        <p className="text-sm text-gray-500 mb-4">Hide patient names (shown as <code className="bg-gray-100 px-1 rounded">*** ***</code>) for screen sharing and demos. Provider names and amounts are unaffected, and your data is never changed.</p>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={redact}
            onChange={toggle}
            className="rounded border-gray-300 text-blue-600 focus:ring-2 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700">Hide patient names</span>
        </label>
      </div>
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
      <div className="bg-white border rounded-lg p-6 shadow-sm mb-6">
        <h2 className="font-semibold text-gray-900 mb-1">Plan Configuration</h2>
        <p className="text-sm text-gray-500 mb-4">Coinsurance percentages for your plan.</p>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-sm text-gray-700">In-Network Coinsurance</label>
            <div className="flex items-center gap-1">
              <input type="number" min={0} max={100} value={inPct}
                onChange={e => { setInPct(Number(e.target.value)); setConfigDirty(true) }}
                className="w-16 border rounded px-2 py-1 text-sm text-right" />
              <span className="text-sm text-gray-500">%</span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <label className="text-sm text-gray-700">Out-of-Network Coinsurance</label>
            <div className="flex items-center gap-1">
              <input type="number" min={0} max={100} value={oonPct}
                onChange={e => { setOonPct(Number(e.target.value)); setConfigDirty(true) }}
                className="w-16 border rounded px-2 py-1 text-sm text-right" />
              <span className="text-sm text-gray-500">%</span>
            </div>
          </div>
          {configDirty && (
            <button onClick={() => configMutation.mutate()}
              disabled={configMutation.isPending}
              className="mt-2 px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
              {configMutation.isPending ? 'Saving...' : 'Save'}
            </button>
          )}
        </div>
      </div>
      <div className="bg-white border rounded-lg p-6 shadow-sm mb-6">
        <h2 className="font-semibold text-gray-900 mb-1">Anthropic API Key</h2>
        <p className="text-sm text-gray-500 mb-3">Used for PDF auto-fill on new submissions.</p>
        <div className="flex items-center gap-2 text-sm">
          {anthropicKey?.configured ? (
            <span className="text-green-700 font-medium">✓ Configured</span>
          ) : (
            <span className="text-gray-500 font-medium">● Not configured</span>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Set it in the terminal: <code className="bg-gray-100 px-1 rounded">backend/.venv/bin/python deploy/store_credentials.py --anthropic</code>
        </p>
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
