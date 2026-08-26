import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import CaseDetail from './pages/CaseDetail'
import DisputeQueue from './pages/DisputeQueue'
import MetricsDashboard from './pages/MetricsDashboard'
import { Button } from './components/ui'

export default function App() {
  return (
    <div className="flex min-h-full">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-[76rem] px-8 py-8">
          <Routes>
            <Route path="/" element={<DisputeQueue />} />
            <Route path="/disputes/:disputeId" element={<CaseDetail />} />
            <Route path="/metrics" element={<MetricsDashboard />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}

function Sidebar() {
  return (
    <aside
      className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col justify-between border-r px-3 py-4 lg:flex"
      style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
    >
      <div>
        <NavLink to="/" className="mb-6 flex items-center gap-2.5 px-2">
          <Mark />
          <span
            className="text-[15px] tracking-[-0.02em]"
            style={{ fontVariationSettings: "'wght' 590" }}
          >
            Recourse
          </span>
        </NavLink>

        <nav className="space-y-0.5">
          <NavItem to="/" icon={<QueueIcon />}>
            Disputes
          </NavItem>
          <NavItem to="/metrics" icon={<ChartIcon />}>
            Performance
          </NavItem>
        </nav>
      </div>

      <div className="space-y-3">
        <Guardrails />
        <ThemeToggle />
      </div>
    </aside>
  )
}

function NavItem({
  to,
  icon,
  children,
}: {
  to: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex items-center gap-2.5 rounded-[var(--radius-control)] px-2 py-1.5 text-[13px] transition duration-[160ms] ${
          isActive
            ? 'bg-[var(--surface-3)] text-[var(--fg)]'
            : 'text-[var(--fg-2)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)]'
        }`
      }
      style={{ fontVariationSettings: "'wght' 510" }}
    >
      <span className="text-[var(--fg-3)]">{icon}</span>
      {children}
    </NavLink>
  )
}

/**
 * CLAUDE.md Section 2's hard constraints, kept visible in the product rather than only in
 * a README. Three lines, no prose — a status readout, not a disclaimer.
 */
function Guardrails() {
  const items = [
    { label: 'Test mode', tone: 'var(--win)' },
    { label: 'Synthetic disputes', tone: 'var(--fg-3)' },
    { label: 'Never auto-submits', tone: 'var(--warn)' },
  ]
  return (
    <ul className="space-y-1.5 px-2">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-2 text-[11.5px] text-[var(--fg-3)]">
          <span className="size-1.5 rounded-full" style={{ background: i.tone }} />
          {i.label}
        </li>
      ))}
    </ul>
  )
}

function ThemeToggle() {
  const [theme, setTheme] = useState(
    () => document.documentElement.dataset.theme ?? 'light',
  )

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('recourse.theme', theme)
  }, [theme])

  return (
    <Button
      variant="ghost"
      size="sm"
      className="w-full justify-start"
      onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      aria-label="Toggle colour theme"
    >
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
      {theme === 'dark' ? 'Light' : 'Dark'}
    </Button>
  )
}

// --- marks ----------------------------------------------------------------------------

function Mark() {
  return (
    <span
      className="grid size-7 place-items-center rounded-[7px]"
      style={{ background: 'var(--fg)', color: 'var(--bg)' }}
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="none" aria-hidden="true">
        <path
          d="M12 3.2l6.8 2.9v5.2c0 4-2.8 7.4-6.8 8.7-4-1.3-6.8-4.7-6.8-8.7V6.1L12 3.2z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <path
          d="M9.2 12.1l2.1 2.1 4.1-4.3"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  )
}

const iconProps = {
  viewBox: '0 0 16 16',
  className: 'size-4',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

function QueueIcon() {
  return (
    <svg {...iconProps}>
      <path d="M2.5 4h11M2.5 8h11M2.5 12h7" />
    </svg>
  )
}

function ChartIcon() {
  return (
    <svg {...iconProps}>
      <path d="M2.5 13.5V9M6.8 13.5V4M11.2 13.5v-6M15 13.5v-9" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg {...iconProps}>
      <path d="M13.5 9.4A5.6 5.6 0 016.6 2.5a5.8 5.8 0 100 11 5.8 5.8 0 006.9-4.1z" />
    </svg>
  )
}

function SunIcon() {
  return (
    <svg {...iconProps}>
      <circle cx="8" cy="8" r="3" />
      <path d="M8 1v1.6M8 13.4V15M15 8h-1.6M2.6 8H1M12.9 3.1l-1.1 1.1M4.2 11.8l-1.1 1.1M12.9 12.9l-1.1-1.1M4.2 4.2L3.1 3.1" />
    </svg>
  )
}

function NotFound() {
  return (
    <div className="surface mx-auto max-w-sm p-8 text-center">
      <h1 className="text-[15px]" style={{ fontVariationSettings: "'wght' 590" }}>
        Page not found
      </h1>
      <NavLink
        to="/"
        className="mt-3 inline-block text-[13px] text-[var(--accent)] hover:underline"
      >
        Back to disputes
      </NavLink>
    </div>
  )
}
