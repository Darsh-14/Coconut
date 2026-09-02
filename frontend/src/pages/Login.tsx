import { ArrowLeft, ArrowRight } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Mark, ThemeToggle } from '../components/ThemeToggle'
import { HEADLINE } from '../lib/headline'
import { paths } from '../lib/routes'
import { DEMO_EMAIL, DEMO_MERCHANT, isSignedIn, signIn } from '../lib/session'

/**
 * The front door.
 *
 * Every field is pre-filled and any value continues, because the alternative — a reviewer
 * meeting a credential wall holding no credentials — is worse than no sign-in at all. The
 * card says outright that this is not an account system rather than implying an
 * authentication that does not exist. See lib/session.ts for the full reasoning.
 *
 * Two columns rather than one centred card: a sign-in screen is a speed bump, so the space
 * beside it is used to say what is being signed into and under what constraints. The right
 * panel is muted and carries no action — it informs, it does not compete with the form.
 */
export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? paths.overview

  const [email, setEmail] = useState(DEMO_EMAIL)
  const [password, setPassword] = useState('demo-merchant')

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
          <span className="w-bold text-[14px] tracking-[-0.02em]">Recourse</span>
        </Link>
        <ThemeToggle compact />
      </header>

      <main className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="grid w-full max-w-[62rem] items-center gap-14 lg:grid-cols-[minmax(0,26rem)_1fr]">
          {/* --- the form -------------------------------------------------------- */}
          <div>
            <h1 className="w-display text-[28px] leading-none">Sign in</h1>
            <p className="mt-2.5 text-[13.5px] text-[var(--fg-2)]">
              Dispute console for {DEMO_MERCHANT}.
            </p>

            <form onSubmit={submit} className="surface mt-6 space-y-4 p-6">
              <Field
                id="email"
                label="Work email"
                type="email"
                value={email}
                onChange={setEmail}
                autoComplete="username"
              />
              <Field
                id="password"
                label="Password"
                type="password"
                value={password}
                onChange={setPassword}
                autoComplete="current-password"
              />

              <button
                type="submit"
                className="pressable focus-ring w-med flex w-full items-center justify-center gap-2 rounded-[var(--radius-control)] px-4 py-2.5 text-[13.5px]"
                style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
              >
                Continue to dashboard
                <ArrowRight size={15} strokeWidth={2} aria-hidden="true" />
              </button>
            </form>

            {/* The honest label. A demo that implied it authenticated would be a small lie
                inside a product whose whole argument is that it does not overstate what it
                knows — so it is stated here rather than left to be discovered. */}
            <div
              className="mt-4 rounded-[var(--radius-control)] border p-4 text-[12.5px] leading-[1.6] text-[var(--fg-2)]"
              style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}
            >
              <span className="w-semi text-[var(--fg)]">
                A front door, not an account system.
              </span>{' '}
              Single-merchant demo, so authentication is deliberately out of scope. The
              fields are pre-filled, any value continues, and no API route is protected by
              this screen.
            </div>

            <Link
              to={paths.landing}
              className="focus-ring mt-5 inline-flex items-center gap-1.5 rounded text-[12.5px] text-[var(--fg-3)] transition-colors hover:text-[var(--fg)]"
            >
              <ArrowLeft size={13} strokeWidth={1.8} aria-hidden="true" />
              Back to the overview
            </Link>
          </div>

          {/* --- what you are signing into --------------------------------------- */}
          <aside className="hidden lg:block">
            <p className="w-display max-w-[20ch] text-[22px] leading-[1.2] text-[var(--fg-2)]">
              Chargeback defence that abstains when the evidence doesn&rsquo;t settle it.
            </p>

            <dl className="mt-8 flex gap-10">
              <div>
                <dt className="num text-[24px] leading-none" style={{ color: 'var(--win)' }}>
                  {HEADLINE.precision}
                </dt>
                <dd className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">precision</dd>
              </div>
              <div>
                <dt className="num text-[24px] leading-none" style={{ color: 'var(--warn)' }}>
                  {HEADLINE.coverage}
                </dt>
                <dd className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">model coverage</dd>
              </div>
              <div>
                <dt className="num text-[24px] leading-none">{HEADLINE.nEvaluated}</dt>
                <dd className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">held-out records</dd>
              </div>
            </dl>

            <ul
              className="mt-9 space-y-2.5 border-t pt-7 text-[12px] text-[var(--fg-3)]"
              style={{ borderColor: 'var(--line)' }}
            >
              {[
                ['Test-mode keys, enforced at startup', 'var(--win)'],
                ['Dispute records are synthetic', 'var(--fg-3)'],
                ['Never auto-submits to Razorpay', 'var(--warn)'],
                ['Defence only — no offensive action', 'var(--win)'],
              ].map(([label, tone]) => (
                <li key={label} className="flex items-center gap-2.5">
                  <span
                    className="size-1 shrink-0 rounded-full"
                    style={{ background: tone }}
                  />
                  {label}
                </li>
              ))}
            </ul>
          </aside>
        </div>
      </main>
    </div>
  )
}

function Field({
  id,
  label,
  type,
  value,
  onChange,
  autoComplete,
}: {
  id: string
  label: string
  type: string
  value: string
  onChange: (v: string) => void
  autoComplete: string
}) {
  return (
    <div>
      <label htmlFor={id} className="w-med mb-1.5 block text-[12px] text-[var(--fg-2)]">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        className="focus-ring w-full rounded-[var(--radius-control)] border px-3 py-2 text-[13.5px] text-[var(--fg)] transition-colors"
        style={{ borderColor: 'var(--line-strong)', background: 'var(--surface-solid)' }}
      />
    </div>
  )
}
