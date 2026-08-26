import { NavLink, Route, Routes } from 'react-router-dom'
import CaseDetail from './pages/CaseDetail'
import DisputeQueue from './pages/DisputeQueue'
import MetricsDashboard from './pages/MetricsDashboard'

export default function App() {
  return (
    <div className="min-h-full">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-3">
          <div className="flex items-baseline gap-3">
            <NavLink to="/" className="text-lg font-semibold tracking-tight">
              Recourse
            </NavLink>
            <span className="hidden text-sm text-slate-500 sm:inline">
              Explainable chargeback defense copilot
            </span>
          </div>

          <nav className="flex items-center gap-1">
            <TabLink to="/">Queue</TabLink>
            <TabLink to="/metrics">Evaluation</TabLink>
          </nav>
        </div>

        {/* Section 2's constraints are load-bearing, so they are stated in the UI, not
            buried in a README the demo audience will not read. */}
        <div className="border-t border-slate-100 bg-slate-50 px-6 py-1.5">
          <p className="mx-auto max-w-6xl text-xs text-slate-500">
            Razorpay <strong>test mode</strong> only · disputes are synthetic · nothing is
            ever submitted to a bank without a human approving it
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-6">
        <Routes>
          <Route path="/" element={<DisputeQueue />} />
          <Route path="/disputes/:disputeId" element={<CaseDetail />} />
          <Route path="/metrics" element={<MetricsDashboard />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  )
}

function TabLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `rounded-md px-3 py-1.5 text-sm font-medium ${
          isActive
            ? 'bg-slate-900 text-white'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
        }`
      }
    >
      {children}
    </NavLink>
  )
}

function NotFound() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <NavLink to="/" className="mt-2 inline-block text-sm text-slate-600 underline">
        Back to the dispute queue
      </NavLink>
    </div>
  )
}
