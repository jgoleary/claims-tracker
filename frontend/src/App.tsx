import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Submissions from './pages/Submissions'
import SubmissionDetail from './pages/SubmissionDetail'
import Matches from './pages/Matches'
import AnthemClaims from './pages/AnthemClaims'
import Totals from './pages/Totals'
import Refresh from './pages/Refresh'
import Settings from './pages/Settings'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="submissions" element={<Submissions />} />
        <Route path="submissions/:id" element={<SubmissionDetail />} />
        <Route path="matches" element={<Matches />} />
        <Route path="anthem-claims" element={<AnthemClaims />} />
        <Route path="totals" element={<Totals />} />
        <Route path="refresh" element={<Refresh />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
