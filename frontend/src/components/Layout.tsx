import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { useYear } from '../context/YearContext'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/submissions', label: 'Submissions' },
  { to: '/matches', label: 'Match Review' },
  { to: '/anthem-claims', label: 'Anthem Claims' },
  { to: '/totals', label: 'Totals' },
  { to: '/refresh', label: 'Refresh' },
  { to: '/settings', label: 'Settings' },
]

const currentYear = new Date().getFullYear()
const YEAR_OPTIONS = Array.from({ length: currentYear - 2023 }, (_, i) => currentYear - i)

export default function Layout() {
  const { year, setYear } = useYear()

  const { data: dash } = useQuery({
    queryKey: ['dashboard', year],
    queryFn: () => api.dashboard.get(year),
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
          <div className="mt-3 flex items-center gap-2">
            <label className="text-xs text-gray-500 shrink-0">Plan year</label>
            <select
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              className="flex-1 bg-gray-800 border border-gray-600 text-gray-200 text-xs rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {YEAR_OPTIONS.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>
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
