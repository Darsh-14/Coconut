import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import CaseDetail from './pages/CaseDetail'
import DisputeQueue from './pages/DisputeQueue'
import MetricsDashboard from './pages/MetricsDashboard'
import Overview from './pages/Overview'

export default function App() {
  return (
    <div className="flex min-h-full">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <MobileBar />
        <div className="mx-auto max-w-[74rem] px-4 py-6 sm:px-8 sm:py-9">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/disputes" element={<DisputeQueue />} />
            <Route path="/disputes/:disputeId" element={<CaseDetail />} />
            <Route path="/metrics" element={<MetricsDashboard />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}

/**
 * Chrome floats above content, so it takes the translucent material. Content surfaces
 * stay opaque — translucency under dense financial text is the documented legibility
 * failure of the style, and Apple's own guidance puts glass on the layer above content
 * rather than behind it.
 */
function Sidebar() {
  return (
    <aside
      className="material sticky top-0 hidden h-screen w-[228px] shrink-0 flex-col justify-between border-r px-3 py-5 lg:flex"
      style={{ borderColor: 'var(--line)' }}
    >
      <div>
        <NavLink to="/" className="mb-7 flex items-center gap-2.5 px-2">
          <Mark />
          <span className="leading-none">
            <span
              className="block text-[15px] tracking-[-0.02em]"
              style={{ fontVariationSettings: "'wght' 600" }}
            >
              Recourse
            </span>
            <span className="mt-1 block text-[10.5px] tracking-[0.04em] text-[var(--fg-3)]">
              CHARGEBACK DEFENCE
            </span>
          </span>
        </NavLink>

        <nav className="space-y-0.5">
          <NavItem to="/" icon={<HomeIcon />}>
            Overview
          </NavItem>
          <NavItem to="/disputes" icon={<QueueIcon />}>
            Disputes
          </NavItem>
          <NavItem to="/metrics" icon={<ChartIcon />}>
            Performance
          </NavItem>
        </nav>
      </div>

      <div className="space-y-4">
        <Guardrails />
        <ThemeToggle />
      </div>
    </aside>
  )
}

/**
 * Navigation for viewports below the sidebar's breakpoint. Carries the same three
 * destinations plus the theme toggle, so no window size is left without a way to move
 * around the app.
 */
function MobileBar() {
  return (
    <div
      className="material sticky top-0 z-30 border-b px-4 py-2.5 lg:hidden"
      style={{ borderColor: 'var(--line)' }}
    >
      <div className="flex items-center justify-between gap-3">
        <NavLink to="/" className="flex shrink-0 items-center gap-2">
          <Mark />
          <span
            className="text-[14px] tracking-[-0.02em]"
            style={{ fontVariationSettings: "'wght' 600" }}
          >
            Recourse
          </span>
        </NavLink>
        <ThemeToggle compact />
      </div>

      <nav className="mt-2.5 flex gap-1 overflow-x-auto">
        <MobileTab to="/">Overview</MobileTab>
        <MobileTab to="/disputes">Disputes</MobileTab>
        <MobileTab to="/metrics">Performance</MobileTab>
      </nav>
    </div>
  )
}

function MobileTab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `pressable shrink-0 rounded-[var(--radius-control)] px-3 py-1.5 text-[12.5px] ${
          isActive
            ? 'bg-[var(--fg)] text-[var(--bg)]'
            : 'text-[var(--fg-2)] hover:bg-[var(--surface-2)]'
        }`
      }
      style={{ fontVariationSettings: "'wght' 510" }}
    >
      {children}
    </NavLink>
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
        `pressable flex items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-2 text-[13px] ${
          isActive
            ? 'bg-[var(--surface-3)] text-[var(--fg)]'
            : 'text-[var(--fg-2)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)]'
        }`
      }
      style={{ fontVariationSettings: "'wght' 510" }}
    >
      {({ isActive }) => (
        <>
          <span className={isActive ? 'text-[var(--fg)]' : 'text-[var(--fg-3)]'}>{icon}</span>
          {children}
        </>
      )}
    </NavLink>
  )
}

/** CLAUDE.md Section 2's hard constraints, as a status readout rather than a disclaimer. */
function Guardrails() {
  const items = [
    { label: 'Test mode', tone: 'var(--win)' },
    { label: 'Synthetic disputes', tone: 'var(--fg-3)' },
    { label: 'Never auto-submits', tone: 'var(--warn)' },
  ]
  return (
    <ul className="space-y-1.5 px-2.5">
      {items.map((i) => (
        <li
          key={i.label}
          className="flex items-center gap-2 text-[11px] tracking-[0.01em] text-[var(--fg-3)]"
        >
          <span className="size-1 rounded-full" style={{ background: i.tone }} />
          {i.label}
        </li>
      ))}
    </ul>
  )
}

function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? 'light')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('recourse.theme', theme)
  }, [theme])

  const isDark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      className={`pressable flex items-center gap-2.5 rounded-[var(--radius-control)] text-[13px] text-[var(--fg-2)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)] ${
        compact ? 'p-2' : 'w-full px-2.5 py-2'
      }`}
      style={{ fontVariationSettings: "'wght' 510" }}
      aria-label="Toggle colour theme"
    >
      <span className="text-[var(--fg-3)]">{isDark ? <SunIcon /> : <MoonIcon />}</span>
      {!compact && (isDark ? 'Light' : 'Dark')}
    </button>
  )
}

// --- marks ----------------------------------------------------------------------------

function Mark() {
  return (
    <span
      className="grid size-8 shrink-0 place-items-center rounded-[9px]"
      style={{
        background: 'linear-gradient(160deg, var(--fg) 0%, color-mix(in srgb, var(--fg) 78%, var(--accent)) 100%)',
        color: 'var(--bg)',
      }}
    >
      <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" aria-hidden="true">
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

function HomeIcon() {
  return (
    <svg {...iconProps}>
      <path d="M2.5 6.8L8 2.5l5.5 4.3v6.2a.5.5 0 01-.5.5H3a.5.5 0 01-.5-.5V6.8z" />
    </svg>
  )
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
        Back to overview
      </NavLink>
    </div>
  )
}
