import { ArrowLeft, ArrowRight } from 'lucide-react'
import { type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Mark, ThemeToggle } from '../components/ThemeToggle'
import { paths } from '../lib/routes'
import { DEMO_MERCHANT, isSignedIn, signIn } from '../lib/session'
import { useDemo } from '../lib/demo'

/**
 * The front door.
 *
 * Demo entry never collects credentials. The local session is a navigation convenience,
 * not authentication. See lib/session.ts.
 *
 * Two columns rather than one centred card: a sign-in screen is a speed bump, so the space
 * beside it is used to say what is being signed into and under what constraints. The right
 * panel is muted and carries no action — it informs, it does not compete with the form.
 */
export default function Login() {
  const demo = useDemo()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? paths.overview

  // Already signed in: skip the door rather than asking twice.
  if (isSignedIn()) return <Navigate to={from} replace />

  function submit(e: FormEvent) {
    e.preventDefault()
    signIn(DEMO_MERCHANT)
    navigate(from, { replace: true })
  }

  return (
    <div className="flex min-h-screen flex-col" style={{ background: 'var(--bg)' }}>
      <header className="flex items-center justify-between px-5 py-4 sm:px-8">
        <Link to={paths.landing} className="focus-ring flex items-center gap-2.5 rounded">
          <Mark size={28} />
          <span className="w-bold text-[14px] tracking-[-0.02em]">Coconut</span>
        </Link>
        <ThemeToggle compact />
      </header>

      <main className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-[26rem]">
          {/* --- the form -------------------------------------------------------- */}
          <div>
            <h1 className="w-display text-[28px] leading-none">Open demo workspace</h1>
            <p className="mt-2.5 text-[13.5px] text-[var(--fg-2)]">
              Dispute console for {DEMO_MERCHANT}.
            </p>

            <form onSubmit={submit} className="surface mt-6 space-y-4 p-6">
              <p className="text-sm text-[var(--fg-2)]">Explore synthetic disputes. No account or password is required.</p>

              <button
                type="submit"
                className="pressable focus-ring w-med flex w-full items-center justify-center gap-2 rounded-[var(--radius-control)] px-4 py-2.5 text-[13.5px]"
                style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
              >
                {demo ? 'Try demo' : 'Continue to dashboard'}
                <ArrowRight size={15} strokeWidth={2} aria-hidden="true" />
              </button>
            </form>

            <Link
              to={paths.landing}
              className="focus-ring mt-5 inline-flex items-center gap-1.5 rounded text-[12.5px] text-[var(--fg-3)] transition-colors hover:text-[var(--fg)]"
            >
              <ArrowLeft size={13} strokeWidth={1.8} aria-hidden="true" />
              Back to the overview
            </Link>
          </div>

        </div>
      </main>
    </div>
  )
}
