import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/submissions', label: 'Submissions' },
  { to: '/matches', label: 'Match Review' },
  { to: '/anthem-claims', label: 'Anthem Claims' },
  { to: '/totals', label: 'Totals' },
  { to: '/refresh', label: 'Refresh' },
  { to: '/settings', label: 'Settings' },
]

export default function Layout() {
  const { data: dash } = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard.get,
    refetchInterval: 60_000,
  })

  const totalAlerts = dash
    ? dash.counts.missing + dash.counts.denied + dash.counts.stale_pending + dash.counts.underpaid
    : 0

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-52 bg-gray-900 text-gray-100 flex flex-col shrink-0">
        <div className="px-4 py-5 border-b border-gray-700">
          <h1 className="text-sm font-bold tracking-wide uppercase text-gray-300">Claims Tracker</h1>
        </div>
        <nav className="flex-1 px-2 py-4 space-y-1">
          {NAV.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center justify-between px-3 py-2 rounded text-sm font-medium transition-colors ${
                  isActive ? 'bg-gray-700 text-white' : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              {label}
              {label === 'Dashboard' && totalAlerts > 0 && (
                <span className="bg-red-500 text-white text-xs rounded-full px-1.5 py-0.5 leading-none">
                  {totalAlerts}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
