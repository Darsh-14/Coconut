import { BarChart3, House, ListFilter, LogOut, Search } from 'lucide-react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Mark, ThemeToggle } from './components/ThemeToggle'
import { paths } from './lib/routes'
import { DEMO_MERCHANT, currentSession, isSignedIn, signOut } from './lib/session'
import CaseDetail from './pages/CaseDetail'
import DisputeQueue from './pages/DisputeQueue'
import Landing from './pages/Landing'
import Login from './pages/Login'
import MetricsDashboard from './pages/MetricsDashboard'
import Overview from './pages/Overview'
import { DemoProvider, DemoWorkspace } from './components/DemoWorkspace'

/**
 * Two shells, not one.
 *
 * The landing and sign-in pages render bare — no sidebar, no app chrome — because they
 * are the product's front door and are seen before anyone has a queue to navigate. The
 * dashboard lives under /app behind that door. Everything inside it kept the paths it had,
 * only prefixed, and those prefixes come from lib/routes so the move was one edit.
 */
export default function App() {
  return (
    <DemoProvider><Routes>
      <Route path={paths.landing} element={<Landing />} />
      <Route path={paths.login} element={<Login />} />
      <Route
        path="/app/*"
        element={
          <RequireSession>
            <AppShell />
          </RequireSession>
        }
      />
      <Route path="*" element={<BareNotFound />} />
    </Routes></DemoProvider>
  )
}

/**
 * Sends an unauthenticated visitor to the front door, remembering where they were headed
 * so a pasted case link survives the round trip.
 *
 * Worth being precise about what this is: a UI convenience, not a security boundary. No
 * API route is protected, and the session is a localStorage flag with no server component
 * — see lib/session.ts for why that is deliberate rather than unfinished.
 */
function RequireSession({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  if (!isSignedIn()) {
    return (
      <Navigate
        to={paths.login}
        state={{ from: location.pathname + location.search }}
        replace
      />
    )
  }
  return <>{children}</>
}

function AppShell() {
  const location = useLocation()
  return (
    <div className="flex min-h-full">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <Sidebar />
      <main id="main-content" className="min-w-0 flex-1" tabIndex={-1}>
        <MobileBar />
        <WorkspaceBar />
        <DemoWorkspace />
        <div className="mx-auto max-w-[74rem] px-4 py-6 sm:px-8 sm:py-9">
          {/* Keyed on the route so recovering from a crash on one page does not leave the
              boundary latched shut when you navigate to another. */}
          <ErrorBoundary key={location.pathname}>
            <Routes>
              <Route index element={<Overview />} />
              <Route path="disputes" element={<DisputeQueue />} />
              <Route path="disputes/:disputeId" element={<CaseDetail />} />
              <Route path="metrics" element={<MetricsDashboard />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </ErrorBoundary>
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
        <NavLink to={paths.overview} className="focus-ring mb-7 flex items-center gap-2.5 rounded px-2">
          <Mark />
          <span className="leading-none">
            <span
              className="block text-[15px] tracking-[-0.02em]"
              style={{ fontVariationSettings: "'wght' 600" }}
            >
              Coconut
            </span>
          </span>
        </NavLink>

        <nav className="space-y-0.5" aria-label="Primary navigation">
          <NavItem to={paths.overview} icon={<House size={16} strokeWidth={1.6} aria-hidden="true" />}>
            Home
          </NavItem>
          <NavItem
            to={paths.disputes}
            icon={<ListFilter size={16} strokeWidth={1.6} aria-hidden="true" />}
          >
            Disputes
          </NavItem>
          <NavItem
            to={paths.metrics}
            icon={<BarChart3 size={16} strokeWidth={1.6} aria-hidden="true" />}
          >
            Performance
          </NavItem>
        </nav>
      </div>

      <div className="space-y-4">
        <div className="space-y-0.5">
          <ThemeToggle />
          <SignOut />
        </div>
        <SignedInAs />
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
        <NavLink to={paths.overview} className="focus-ring flex shrink-0 items-center gap-2 rounded">
          <Mark size={28} />
          <span
            className="text-[14px] tracking-[-0.02em]"
            style={{ fontVariationSettings: "'wght' 600" }}
          >
            Coconut
          </span>
        </NavLink>
        <div className="flex items-center gap-1">
          <ThemeToggle compact />
          <SignOut compact />
        </div>
      </div>

      <nav className="mt-2.5 flex gap-1 overflow-x-auto" aria-label="Primary navigation">
        <MobileTab to={paths.overview}>Home</MobileTab>
        <MobileTab to={paths.disputes}>Disputes</MobileTab>
        <MobileTab to={paths.metrics}>Performance</MobileTab>
      </nav>
    </div>
  )
}

function MobileTab({ to, children }: { to: string; children: React.ReactNode }) {
  const location = useLocation()
  const selected = navSelected(to, location.pathname)
  return (
    <NavLink
      to={to}
      end={to === paths.overview}
      aria-current={selected ? 'page' : false}
      className={() =>
        `pressable focus-ring shrink-0 rounded-[var(--radius-control)] px-3 py-1.5 text-[12.5px] ${
          selected
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
  const location = useLocation()
  const selected = navSelected(to, location.pathname)
  return (
    <NavLink
      to={to}
      end={to === paths.overview}
      aria-current={selected ? 'page' : false}
      className={() =>
        `pressable focus-ring flex items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-2 text-[13px] ${
          selected
            ? 'bg-[var(--surface-3)] text-[var(--fg)]'
            : 'text-[var(--fg-2)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)]'
        }`
      }
      style={{ fontVariationSettings: "'wght' 510" }}
    >
      {() => (
        <>
          <span className={selected ? 'text-[var(--fg)]' : 'text-[var(--fg-3)]'}>{icon}</span>
          {children}
        </>
      )}
    </NavLink>
  )
}

function navSelected(to: string, pathname: string) {
  return pathname === to || (to === paths.disputes && pathname.startsWith(`${paths.disputes}/`))
}

function WorkspaceBar() {
  const navigate = useNavigate()
  return (
    <header className="flex justify-end border-b px-4 py-3 sm:px-8" style={{ borderColor: 'var(--line)' }}>
      <form className="flex w-full items-center gap-2 sm:w-72" role="search" onSubmit={(event) => {
        event.preventDefault()
        const query = String(new FormData(event.currentTarget).get('q') ?? '').trim()
        navigate(query ? `${paths.disputes}?q=${encodeURIComponent(query)}` : paths.disputes)
      }}>
        <input name="q" type="search" aria-label="Search workspace" placeholder="Search disputes or payments" className="focus-ring min-w-0 flex-1 rounded bg-[var(--surface-2)] px-3 py-2 text-xs" />
        <button type="submit" aria-label="Search" className="focus-ring rounded p-2 text-[var(--fg-2)]"><Search size={16} /></button>
      </form>
    </header>
  )
}

function SignOut({ compact = false }: { compact?: boolean }) {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      onClick={() => {
        signOut()
        navigate(paths.landing, { replace: true })
      }}
      className={`pressable focus-ring flex items-center gap-2.5 rounded-[var(--radius-control)] text-[13px] text-[var(--fg-2)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)] ${
        compact ? 'p-2' : 'w-full px-2.5 py-2'
      }`}
      style={{ fontVariationSettings: "'wght' 510" }}
      aria-label="Sign out"
    >
      <span className="text-[var(--fg-3)]">
        <LogOut size={16} strokeWidth={1.6} aria-hidden="true" />
      </span>
      {!compact && 'Sign out'}
    </button>
  )
}

function SignedInAs() {
  const session = currentSession()
  return (
    <p className="px-2.5 text-[10.5px] leading-snug text-[var(--fg-3)]">
      {session?.merchant ?? DEMO_MERCHANT}
    </p>
  )
}

function NotFound() {
  return (
    <div className="surface mx-auto max-w-sm p-8 text-center">
      <h1 className="text-[15px]" style={{ fontVariationSettings: "'wght' 590" }}>
        Page not found
      </h1>
      <NavLink
        to={paths.overview}
        className="focus-ring mt-3 inline-block rounded text-[13px] text-[var(--accent)] hover:underline"
      >
        Back to overview
      </NavLink>
    </div>
  )
}

/** Outside the shell: an unknown top-level path has no sidebar to sit beside. */
function BareNotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center p-6" style={{ background: 'var(--bg)' }}>
      <div className="surface max-w-sm p-8 text-center">
        <h1 className="text-[15px]" style={{ fontVariationSettings: "'wght' 590" }}>
          Page not found
        </h1>
        <NavLink
          to={paths.landing}
          className="focus-ring mt-3 inline-block rounded text-[13px] text-[var(--accent)] hover:underline"
        >
          Back to the front page
        </NavLink>
      </div>
    </div>
  )
}
