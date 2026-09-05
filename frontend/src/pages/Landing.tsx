import {
  ArrowRight,
  ClipboardCheck,
  Cpu,
  FileSearch,
  Gauge,
  Landmark,
  ListChecks,
  PenLine,
  Radio,
  Scale,
  ShieldCheck,
  Wallet,
} from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Mark, ThemeToggle } from '../components/ThemeToggle'
import { HEADLINE, RECORDED } from '../lib/headline'
import { paths } from '../lib/routes'
import { isSignedIn } from '../lib/session'

/**
 * The public front page.
 *
 * ARRANGEMENT — modelled on razorpay.com's section order at the user's direction: sticky
 * nav with the auth actions right, a hero stating breadth rather than a slogan, a trust
 * line under it, a product shot, grouped capability cards, alternating feature bands, a
 * solutions table, a developer section with a real curl, measured numbers, FAQ, footer.
 * Structure only — none of Razorpay's brand, palette, copy or imagery is reproduced.
 *
 * COPY — every block here is deliberately short. The first version carried three-sentence
 * bodies on twelve cards and paragraph-length FAQ answers, and read as filler. A card that
 * needs three sentences is a card whose title is not doing its job.
 *
 * IMAGERY — the three screenshots are the running application, captured from the seeded
 * database in both themes. Not mockups: nothing here depicts a feature that does not
 * exist, and the figures inside the images match the figures printed beside them.
 */
export default function Landing() {
  const entry = isSignedIn() ? paths.overview : paths.login
  const root = useReveal<HTMLDivElement>()

  return (
    <div ref={root} className="min-h-screen" style={{ background: 'var(--bg)' }}>
      <Nav entry={entry} />

      <main>
        {/* --- hero ---------------------------------------------------------------- */}
        <Band>
          <div className="grid gap-12 py-16 sm:py-24 lg:grid-cols-[1.1fr_1fr] lg:items-center">
            <div className="reveal">
              <h1 className="w-display max-w-[15ch] text-[44px] leading-[1.0] sm:text-[64px]">
                Know which chargebacks are worth fighting.
              </h1>
              <p className="mt-6 max-w-[46ch] text-[16px] leading-[1.55] text-[var(--fg-2)]">
                Coconut checks the evidence against the bank&rsquo;s claim and only contests
                when the case is clear.
              </p>

              <div className="mt-8 flex flex-wrap items-center gap-2.5">
                <Primary to={entry}>Open the dashboard</Primary>
                <Secondary href="#how">How it works</Secondary>
              </div>

              <div className="mt-11 flex flex-wrap gap-x-10 gap-y-5">
                <Stat
                  value={HEADLINE.precision}
                  label={`observed precision · ${RECORDED.contestSupport} contests`}
                  tone="var(--win)"
                />
                <Stat value={HEADLINE.coverage} label="model coverage" tone="var(--warn)" />
                <Stat value={String(HEADLINE.nEvaluated)} label="held-out records" />
              </div>
            </div>

            <div className="reveal">
              <VerdictPreview />
            </div>
          </div>
        </Band>

        {/* --- the product, immediately -------------------------------------------- */}
        <Band tinted>
          <div className="py-14">
            <Shot name="queue" alt="The Coconut dispute queue" priority />
          </div>
        </Band>

        {/* --- capabilities -------------------------------------------------------- */}
        <Band id="how" tinted>
          <Section title="What&rsquo;s inside">
            <Group label="Decide">
              <Card icon={<Cpu size={16} strokeWidth={1.7} />} title="Verification engine">
                Two checks per item: does it address the claim, and does it prove it.
              </Card>
              <Card icon={<Scale size={16} strokeWidth={1.7} />} title="Decision aggregator">
                Clear rules, with a weakest-link confidence check.
              </Card>
              <Card icon={<Gauge size={16} strokeWidth={1.7} />} title="Risk-budget calibration">
                Choose the error budget and let the threshold follow.
              </Card>
              <Card icon={<FileSearch size={16} strokeWidth={1.7} />} title="Span explainability">
                The exact sentence that drove the call is highlighted inline.
              </Card>
            </Group>

            <Group label="India-native rails" cols={3}>
              <Card icon={<Landmark size={16} strokeWidth={1.7} />} title="URCS forecast">
                Predicts NPCI auto-rejection before you act.
              </Card>
              <Card icon={<Wallet size={16} strokeWidth={1.7} />} title="Dispute budget">
                30-day counts against the CD1 and CD2 caps.
              </Card>
              <Card icon={<ShieldCheck size={16} strokeWidth={1.7} />} title="Dated provenance">
                Rules carry the date they were checked against NPCI circulars.
              </Card>
            </Group>

            <Group label="Operate">
              <Card icon={<ListChecks size={16} strokeWidth={1.7} />} title="Dispute queue">
                Deadlines, rails, and the current assessment.
              </Card>
              <Card icon={<PenLine size={16} strokeWidth={1.7} />} title="Representment drafting">
                Drafts the packet after the decision is already made.
              </Card>
              <Card icon={<ClipboardCheck size={16} strokeWidth={1.7} />} title="Audit trail">
                Every decision is logged and replayable.
              </Card>
              <Card icon={<Radio size={16} strokeWidth={1.7} />} title="Signed webhooks">
                Raw-body validation with a fail-closed default.
              </Card>
            </Group>
          </Section>
        </Band>

        {/* --- feature: the dial ---------------------------------------------------- */}
        <Band>
          <Feature
            eyebrow="RISK-BUDGET PROTOTYPE"
            title="Name a risk budget, not a threshold"
            shot="metrics"
            alt="The risk budget dial showing calibrated threshold, coverage and observed contest-error rate"
          >
            <p>
              Set the maximum contest-error rate you can tolerate, then let the system pick the
              threshold and report the coverage trade-off.
            </p>
            <p>
              If the budget is not achievable, it says so instead of hiding behind a default.
            </p>
          </Feature>
        </Band>

        {/* --- feature: UPI --------------------------------------------------------- */}
        <Band tinted>
          <Feature
            eyebrow="UPI RAILS"
            title="Some disputes resolve without you"
            shot="case"
            alt="A case showing the NPCI dispute budget, the recommendation and its confidence"
            flip
          >
            <p>
              NPCI caps UPI disputes at a fixed rate over 30 days. URCS auto-rejects the
              overflow without a human step.
            </p>
            <p>
              Coconut forecasts that outcome and tells you when the representment fee is not worth it.
            </p>
          </Feature>
        </Band>

        {/* --- outcomes ------------------------------------------------------------- */}
        <Band>
          <Section title="Four outcomes, each with a rule you can read">
            <div className="reveal surface overflow-x-auto">
              <table className="w-full min-w-[42rem] text-left text-[12.5px]">
                <thead
                  className="border-b text-[11px] tracking-[0.03em] text-[var(--fg-3)]"
                  style={{ borderColor: 'var(--line)' }}
                >
                  <tr>
                    <th className="px-4 py-3 font-normal">Outcome</th>
                    <th className="px-4 py-3 font-normal">Trigger</th>
                    <th className="px-4 py-3 font-normal">You do</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--line)]">
                  <Row
                    tone="var(--win)"
                    name="CONTEST"
                    trigger="All support verdicts clear the threshold and use at least two evidence types."
                    action="Approve the draft."
                  />
                  <Row
                    tone="var(--risk)"
                    name="ACCEPT"
                    trigger="The evidence is against the merchant at or above threshold."
                    action="Concede it."
                  />
                  <Row
                    tone="var(--warn)"
                    name="NEEDS_HUMAN_REVIEW"
                    trigger="The case stays ambiguous or the chosen risk budget cannot support it."
                    action="Review manually."
                  />
                  <Row
                    tone="var(--fg-3)"
                    name="NO_ACTION_NEEDED"
                    trigger="URCS is likely to auto-reject under CD1 or CD2."
                    action="Do nothing."
                  />
                </tbody>
              </table>
            </div>
          </Section>
        </Band>

        {/* --- developers ----------------------------------------------------------- */}
        <Band tinted id="developers">
          <Section title="For developers" sub="API-first, no hidden state.">
            <div className="grid gap-8 lg:grid-cols-[0.9fr_1.1fr]">
              <ul className="reveal space-y-2.5">
                {[
                  ['GET', '/disputes', 'the queue'],
                  ['GET', '/disputes/{id}', 'case, decision, audit trail'],
                  ['POST', '/disputes/{id}/decide', 'run the engine'],
                  ['POST', '/disputes/{id}/approve', 'human approval'],
                  ['GET', '/disputes/{id}/urcs-forecast', 'NPCI cap forecast'],
                  ['POST', '/calibrate', 'threshold from a risk budget'],
                  ['GET', '/verify-guarantee', 'empirical check (legacy path)'],
                  ['POST', '/evaluate', 'held-out metrics'],
                ].map(([method, path, note]) => (
                  <li key={path} className="flex flex-wrap items-baseline gap-x-2.5">
                    <span
                      className="num w-[2.6rem] shrink-0 text-[10px]"
                      style={{ color: method === 'GET' ? 'var(--win)' : 'var(--accent)' }}
                    >
                      {method}
                    </span>
                    <code className="num text-[12px] text-[var(--fg)]">{path}</code>
                    <span className="text-[11.5px] text-[var(--fg-3)]">{note}</span>
                  </li>
                ))}
              </ul>

              <div className="reveal">
                <div
                  className="overflow-x-auto rounded-[var(--radius-card)] border p-4"
                  style={{ borderColor: 'var(--line)', background: 'var(--surface-solid)' }}
                >
                  <pre className="num text-[11.5px] leading-[1.7] text-[var(--fg-2)]">
{`$ curl -X POST localhost:8000/disputes/disp_synthetic_0168/decide

{
  "recommendation": "CONTEST",
  "confidence": 0.50,
  "calibrated_threshold_used": 0.50,
  "claim_verdicts": [
    { "evidence_index": 0,
      "label": "support",
      "confidence": 0.50,
      "highlighted_span": "OTP captured at delivery" },
    { "evidence_index": 1,
      "label": "support",
      "confidence": 0.50,
      "highlighted_span": "Three prior orders to this address, none disputed." }
  ],
  "model_version": "cross-encoder/nli-deberta-v3-base@6c749ce3425cd33b46d187e45b92bbf96ee12ec7"
}`}
                  </pre>
                </div>
                <p className="mt-3 text-[11.5px] text-[var(--fg-3)]">
                  The threshold is stored with the decision — otherwise it isn&rsquo;t
                  reproducible.
                </p>
              </div>
            </div>
          </Section>
        </Band>

        {/* --- measured ------------------------------------------------------------- */}
        <Band>
          <Section
            title="Measured on a separate held-out set"
            sub={`${HEADLINE.nEvaluated} held-out records · ${HEADLINE.measuredOn}`}
          >
            <div className="grid gap-10 lg:grid-cols-2">
              <div className="reveal surface overflow-hidden">
                <table className="w-full text-left text-[12.5px]">
                  <tbody className="divide-y divide-[var(--line)]">
                    {[
                      ['TP', RECORDED.matrix.tp, 'CONTEST, and it was winnable'],
                      ['FP', RECORDED.matrix.fp, 'CONTEST, and it was not'],
                      ['FN', RECORDED.matrix.fn, 'ACCEPT, but it was winnable'],
                      ['TN', RECORDED.matrix.tn, 'ACCEPT, correctly'],
                      ['Human', RECORDED.matrix.flagged_human, 'deferred rather than guessed'],
                      ['URCS', RECORDED.autoResolved, 'resolved by NPCI rules'],
                    ].map(([key, count, meaning]) => (
                      <tr key={String(key)}>
                        <td className="num px-4 py-2.5 text-[var(--fg-3)]">{key}</td>
                        <td className="num px-2 py-2.5 text-[var(--fg)]">{count}</td>
                        <td className="px-4 py-2.5 text-[11.5px] text-[var(--fg-3)]">
                          {meaning}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="reveal space-y-4 text-[13px] leading-[1.65] text-[var(--fg-2)]">
                <p>
                  The model decides{' '}
                  {RECORDED.nEvaluated - RECORDED.matrix.flagged_human - RECORDED.autoResolved}{' '}
                  cases on the evidence; {RECORDED.matrix.flagged_human} are deferred and{' '}
                  {RECORDED.autoResolved} are resolved by NPCI rules.
                </p>
                <p>
                  <span className="w-semi text-[var(--fg)]">
                    Small sample, limited coverage.
                  </span>{' '}
                  Precision is based on {RECORDED.contestSupport} contests. The recorded 95%
                  interval is {(RECORDED.precisionWilson95.lower * 100).toFixed(1)}%–100%.
                </p>
                <p className="text-[12px] text-[var(--fg-3)]">
                  False-positive cost at this operating point: ₹
                  {HEADLINE.falsePositiveCostInr.toLocaleString('en-IN')}.
                </p>
              </div>
            </div>
          </Section>
        </Band>

        {/* --- faq ------------------------------------------------------------------ */}
        <Band tinted id="faq">
          <Section title="Questions you should ask">
            <div className="reveal grid gap-x-12 lg:grid-cols-2">
              <Faq q="Are these real Razorpay disputes?">
                No. The dispute records are generated and the payment underneath is a real
                test-mode payment.
              </Faq>
              <Faq q="Does it ever submit to Razorpay or a bank?">
                Never. It logs the payload as a would-submit action and stops.
              </Faq>
              <Faq q="Why isn't the decision an LLM?">
                Determinism and cost. A local cross-encoder is free to run at scale and gives
                the same answer every time.
              </Faq>
              <Faq q="Is the sign-in real authentication?">
                No. It is a single-merchant demo with pre-filled fields and no protected API.
              </Faq>
              <Faq q="What does the risk check show?">
                It shows whether the observed contest-error rate stayed under the chosen budget.
              </Faq>
              <Faq q="What did calibration reveal?">
                That the tightest budget this data supports is not a strong operational promise.
              </Faq>
            </div>
          </Section>
        </Band>

        {/* --- cta ------------------------------------------------------------------ */}
        <Band>
          <div className="reveal py-20 text-center">
            <h2 className="w-display text-[30px] leading-tight">See it decide a case end to end.</h2>
            <p className="mx-auto mt-3 max-w-[38ch] text-[13.5px] text-[var(--fg-2)]">
              The seeded queue is ready to review.
            </p>
            <div className="mt-7 flex justify-center">
              <Primary to={entry} large>
                Open the dashboard
              </Primary>
            </div>
          </div>
        </Band>
      </main>

      <Footer entry={entry} />
    </div>
  )
}

/* -- motion ------------------------------------------------------------------------ */

/**
 * Reveals `.reveal` elements as they come within the fold: 200ms, 10px, 35ms stagger.
 *
 * A rAF-throttled scroll sweep rather than an IntersectionObserver, and that is a fix
 * rather than a preference. An observer only fires when an intersection ratio *changes*.
 * Jump the page instantly — the End key, or the #developers and #faq anchors in this
 * page's own nav — and a skipped element goes from "not intersecting, below" to "not
 * intersecting, above" without ever crossing a threshold. The callback never runs for it,
 * so it stays invisible for the rest of the session, and the visitor who scrolls back up
 * finds blank bands. Measured: 4 of 37 elements stranded after a single jump to the
 * bottom.
 *
 * A sweep asks a different question — "is this above the fold yet?" — which cannot be
 * skipped, because it is evaluated against wherever the page actually is now.
 *
 * The hidden state lives behind [data-reveal='on'], set in a layout effect before paint.
 * If that never runs, nothing is ever hidden and the page degrades to static rather than
 * to blank. Under prefers-reduced-motion the CSS block is skipped entirely.
 */
function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null)

  useLayoutEffect(() => {
    if (ref.current) ref.current.dataset.reveal = 'on'
  }, [])

  useEffect(() => {
    const root = ref.current
    if (!root) return

    const pending = new Set(root.querySelectorAll<HTMLElement>('.reveal'))
    let frame = 0

    const teardown = () => {
      window.removeEventListener('scroll', request)
      window.removeEventListener('resize', request)
      if (frame) cancelAnimationFrame(frame)
      frame = 0
    }

    const sweep = () => {
      frame = 0
      const fold = window.innerHeight * 0.94
      let staggered = 0
      pending.forEach((el) => {
        if (el.getBoundingClientRect().top >= fold) return
        el.style.transitionDelay = `${Math.min(staggered++, 4) * 35}ms`
        el.classList.add('shown')
        pending.delete(el)
      })
      if (pending.size === 0) teardown()
    }

    function request() {
      if (!frame) frame = requestAnimationFrame(sweep)
    }

    window.addEventListener('scroll', request, { passive: true })
    window.addEventListener('resize', request, { passive: true })
    sweep()
    return teardown
  }, [])

  return ref
}

/* -- layout ------------------------------------------------------------------------ */

function Nav({ entry }: { entry: string }) {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header
      className={`sticky top-0 z-30 border-b transition-colors duration-200 ${
        scrolled ? 'material' : ''
      }`}
      style={{ borderColor: scrolled ? 'var(--line)' : 'transparent' }}
    >
      <div className="mx-auto flex h-14 max-w-[72rem] items-center justify-between gap-4 px-5 sm:px-8">
        <div className="flex items-center gap-2.5">
          <Mark size={26} />
          <span className="w-bold text-[14.5px] tracking-[-0.02em]">Coconut</span>
        </div>

        <nav className="hidden items-center gap-0.5 md:flex">
          <NavAnchor href="#how">Product</NavAnchor>
          <NavAnchor href="#developers">Developers</NavAnchor>
          <NavAnchor href="#faq">FAQ</NavAnchor>
        </nav>

        <div className="flex items-center gap-1">
          <ThemeToggle compact />
          <Link
            to={paths.login}
            className="pressable focus-ring w-med hidden rounded-[var(--radius-control)] px-3 py-1.5 text-[13px] text-[var(--fg-2)] transition-colors hover:text-[var(--fg)] sm:inline-flex"
          >
            Open demo
          </Link>
          <Link
            to={entry}
            className="pressable focus-ring w-med rounded-[var(--radius-control)] px-3.5 py-1.5 text-[13px]"
            style={{ background: 'var(--fg)', color: 'var(--bg)' }}
          >
            Open dashboard
          </Link>
        </div>
      </div>
    </header>
  )
}

function NavAnchor({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      className="focus-ring w-med rounded-[var(--radius-control)] px-3 py-1.5 text-[13px] text-[var(--fg-2)] transition-colors hover:text-[var(--fg)]"
    >
      {children}
    </a>
  )
}

function Primary({
  to,
  large = false,
  children,
}: {
  to: string
  large?: boolean
  children: React.ReactNode
}) {
  return (
    <Link
      to={to}
      className={`pressable focus-ring w-med inline-flex items-center gap-2 rounded-[var(--radius-control)] ${
        large ? 'px-5 py-3 text-[14px]' : 'px-4 py-2.5 text-[13.5px]'
      }`}
      style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
    >
      {children}
      <ArrowRight size={15} strokeWidth={2} aria-hidden="true" />
    </Link>
  )
}

function Secondary({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      className="pressable focus-ring w-med inline-flex items-center rounded-[var(--radius-control)] border px-4 py-2.5 text-[13.5px] text-[var(--fg-2)] transition-colors hover:text-[var(--fg)]"
      style={{ borderColor: 'var(--line-strong)' }}
    >
      {children}
    </a>
  )
}

function Band({
  children,
  tinted = false,
  id,
}: {
  children: React.ReactNode
  tinted?: boolean
  id?: string
}) {
  return (
    <div
      id={id}
      className={`border-t ${id ? 'scroll-mt-14' : ''}`}
      style={{
        borderColor: 'var(--line)',
        background: tinted ? 'var(--surface-2)' : 'transparent',
      }}
    >
      <div className="mx-auto max-w-[72rem] px-5 sm:px-8">{children}</div>
    </div>
  )
}

function Section({
  title,
  sub,
  children,
}: {
  title: React.ReactNode
  sub?: string
  children: React.ReactNode
}) {
  return (
    <section className="py-16">
      <div className="reveal">
        <h2 className="w-display max-w-[24ch] text-[24px] leading-tight">{title}</h2>
        {sub && <p className="mt-2 text-[13px] text-[var(--fg-3)]">{sub}</p>}
      </div>
      <div className="mt-9">{children}</div>
    </section>
  )
}

/** Alternating text/screenshot row — the shape razorpay.com uses for its feature bands. */
function Feature({
  eyebrow,
  title,
  shot,
  alt,
  flip = false,
  children,
}: {
  eyebrow: string
  title: string
  shot: string
  alt: string
  flip?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="grid items-center gap-10 py-16 lg:grid-cols-[0.85fr_1.15fr]">
      <div className={`reveal ${flip ? 'lg:order-2' : ''}`}>
        <p className="w-semi text-[10.5px] tracking-[0.07em] text-[var(--accent)]">{eyebrow}</p>
        <h2 className="w-display mt-3 max-w-[16ch] text-[26px] leading-[1.12]">{title}</h2>
        <div className="mt-4 space-y-3 text-[13.5px] leading-[1.6] text-[var(--fg-2)]">
          {children}
        </div>
      </div>
      <div className={flip ? 'lg:order-1' : ''}>
        <Shot name={shot} alt={alt} />
      </div>
    </div>
  )
}

/**
 * A screenshot of the running app, shipped once per theme. Both sit in the DOM and CSS
 * hides the mismatched one (see index.css) — a dark screenshot on a light page is the
 * clearest possible tell that an image was pasted in rather than taken from the product.
 * Dimensions are explicit so the image reserves its space and nothing below it jumps.
 */
function Shot({ name, alt, priority = false }: { name: string; alt: string; priority?: boolean }) {
  const common = {
    width: 1485,
    height: 915,
    alt,
    loading: priority ? ('eager' as const) : ('lazy' as const),
    decoding: 'async' as const,
    className: 'block w-full rounded-[var(--radius-card)]',
    style: { boxShadow: 'var(--shadow-pop)' },
  }
  return (
    <div className="reveal">
      <img {...common} data-shot="dark" src={`/shots/${name}-dark.png`} />
      <img {...common} data-shot="light" src={`/shots/${name}-light.png`} />
    </div>
  )
}

/* -- pieces ------------------------------------------------------------------------ */

function Stat({ value, label, tone }: { value: string; label: string; tone?: string }) {
  return (
    <div>
      <div
        className="num text-[28px] leading-none tracking-[-0.03em]"
        style={{ color: tone ?? 'var(--fg)' }}
      >
        {value}
      </div>
      <div className="mt-2 text-[11.5px] text-[var(--fg-3)]">{label}</div>
    </div>
  )
}

function Group({
  label,
  cols = 4,
  children,
}: {
  label: string
  cols?: 3 | 4
  children: React.ReactNode
}) {
  return (
    <div className="mb-10 last:mb-0">
      <h3 className="reveal w-semi mb-3.5 text-[10.5px] tracking-[0.07em] text-[var(--fg-3)]">
        {label.toUpperCase()}
      </h3>
      <div
        className={`grid gap-3 sm:grid-cols-2 ${cols === 3 ? 'lg:grid-cols-3' : 'lg:grid-cols-4'}`}
      >
        {children}
      </div>
    </div>
  )
}

function Card({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="reveal surface lift p-4">
      <span className="text-[var(--fg-3)]">{icon}</span>
      <h4 className="w-semi mt-3 text-[13px]">{title}</h4>
      <p className="mt-1.5 text-[12px] leading-[1.55] text-[var(--fg-3)]">{children}</p>
    </div>
  )
}

function Row({
  tone,
  name,
  trigger,
  action,
}: {
  tone: string
  name: string
  trigger: string
  action: string
}) {
  return (
    <tr>
      <td className="px-4 py-3.5 align-top">
        <span className="flex items-center gap-2">
          <span className="size-1.5 shrink-0 rounded-full" style={{ background: tone }} />
          <span className="num text-[11px]" style={{ color: tone }}>
            {name}
          </span>
        </span>
      </td>
      <td className="px-4 py-3.5 align-top text-[var(--fg-2)]">{trigger}</td>
      <td className="px-4 py-3.5 align-top text-[var(--fg-3)]">{action}</td>
    </tr>
  )
}

/** Native details/summary: keyboard operable and correctly announced, with no JS. */
function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <details className="group border-b py-4" style={{ borderColor: 'var(--line)' }}>
      <summary className="focus-ring w-semi flex cursor-pointer list-none items-start justify-between gap-4 rounded text-[13.5px]">
        {q}
        <span
          className="mt-0.5 shrink-0 text-[var(--fg-3)] transition-transform duration-200 group-open:rotate-45"
          aria-hidden="true"
        >
          +
        </span>
      </summary>
      <p className="mt-2.5 max-w-[46ch] text-[12.5px] leading-[1.6] text-[var(--fg-2)]">
        {children}
      </p>
    </details>
  )
}

function Footer({ entry }: { entry: string }) {
  return (
    <footer className="border-t" style={{ borderColor: 'var(--line)' }}>
      <div className="mx-auto max-w-[72rem] px-5 py-12 sm:px-8">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <div className="flex items-center gap-2.5">
              <Mark size={24} />
              <span className="w-semi text-[13.5px]">Coconut</span>
            </div>
            <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
              Explainable chargeback defence,
              <br />
              built for Indian payment rails.
            </p>
          </div>

          <FooterCol
            title="Product"
            items={[
              ['Overview', '#how'],
              ['Developers', '#developers'],
              ['FAQ', '#faq'],
            ]}
          />

          <FooterList
            title="Stack"
            items={[
              'FastAPI · Pydantic · SQLAlchemy',
              'nli-deberta-v3-base',
              'React · Vite · Tailwind',
              'razorpay, test mode only',
            ]}
          />

          <div>
            <h3 className="w-semi text-[10.5px] tracking-[0.07em] text-[var(--fg-3)]">
              GUARDRAILS
            </h3>
            <ul className="mt-3.5 space-y-2 text-[11.5px] text-[var(--fg-3)]">
              {[
                ['Test-mode keys enforced at startup', 'var(--win)'],
                ['Dispute records are synthetic', 'var(--fg-3)'],
                ['Never auto-submits', 'var(--warn)'],
                ['Defence only', 'var(--win)'],
              ].map(([label, tone]) => (
                <li key={label} className="flex items-start gap-2">
                  <span
                    className="mt-[5px] size-1 shrink-0 rounded-full"
                    style={{ background: tone }}
                  />
                  {label}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div
          className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t pt-6 text-[11.5px] text-[var(--fg-3)]"
          style={{ borderColor: 'var(--line)' }}
        >
          <span>Dispute records are synthetic. Backing payments are real, in test mode.</span>
          <Link
            to={entry}
            className="focus-ring inline-flex items-center gap-1.5 rounded transition-colors hover:text-[var(--fg)]"
          >
            Open dashboard
            <ArrowRight size={13} strokeWidth={1.8} aria-hidden="true" />
          </Link>
        </div>
      </div>
    </footer>
  )
}

function FooterCol({ title, items }: { title: string; items: string[][] }) {
  return (
    <div>
      <h3 className="w-semi text-[10.5px] tracking-[0.07em] text-[var(--fg-3)]">
        {title.toUpperCase()}
      </h3>
      <ul className="mt-3.5 space-y-2">
        {items.map(([label, href]) => (
          <li key={label}>
            <a
              href={href}
              className="focus-ring rounded text-[11.5px] text-[var(--fg-3)] transition-colors hover:text-[var(--fg)]"
            >
              {label}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

function FooterList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h3 className="w-semi text-[10.5px] tracking-[0.07em] text-[var(--fg-3)]">
        {title.toUpperCase()}
      </h3>
      <ul className="mt-3.5 space-y-2 text-[11.5px] text-[var(--fg-3)]">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The hero's right column: one seeded case in the same visual language the case page uses.
 * Static, and consistent by design — the values match the curl sample further down, and
 * the overall 0.50 is the MINIMUM of the two verdicts rather than their average, which
 * puts the aggregation rule on screen before anyone reads a word about it.
 */
function VerdictPreview() {
  return (
    <div className="surface overflow-hidden">
      <div
        className="flex items-center justify-between border-b px-4 py-3"
        style={{ borderColor: 'var(--line)' }}
      >
        <span className="num text-[11.5px] text-[var(--fg-3)]">disp_synthetic_0168</span>
        <span
          className="rounded-full px-2 py-0.5 text-[10.5px]"
          style={{ background: 'var(--surface-3)', color: 'var(--fg-2)' }}
        >
          chargeback
        </span>
      </div>

      <div className="border-b px-4 py-4" style={{ borderColor: 'var(--line)' }}>
        <div className="flex items-baseline justify-between gap-3">
          <span className="flex items-center gap-2">
            <span className="size-1.5 rounded-full" style={{ background: 'var(--win)' }} />
            <span className="num text-[12px]" style={{ color: 'var(--win)' }}>
              CONTEST
            </span>
          </span>
          <span className="num text-[11.5px] text-[var(--fg-3)]">0.50</span>
        </div>
        <div
          className="mt-3 h-1 overflow-hidden rounded-full"
          style={{ background: 'var(--surface-3)' }}
        >
          <div
            className="meter-fill h-full rounded-full"
            style={{ width: '50%', background: 'var(--win)' }}
          />
        </div>
        <p className="mt-2 text-[10.5px] text-[var(--fg-3)]">the weakest link, not the average</p>
      </div>

      <div className="border-b px-4 py-3.5" style={{ borderColor: 'var(--line)' }}>
        <p className="w-semi text-[10px] tracking-[0.06em] text-[var(--fg-3)]">CLAIM</p>
        <p className="mt-1.5 text-[12px] leading-[1.55] text-[var(--fg-2)]">
          Goods never received at the delivery address given at checkout.
        </p>
      </div>

      <div className="space-y-4 p-4">
        <EvidenceLine type="delivery_proof" confidence="0.90">
          Courier POD signed 14:22.{' '}
          <mark
            className="rounded px-1"
            style={{ background: 'var(--warn-soft)', color: 'var(--fg)' }}
          >
            OTP captured at delivery, ID matching KYC
          </mark>
          {'.'}
        </EvidenceLine>
        <EvidenceLine type="order_history" confidence="0.50">
          Three prior orders to this address, none disputed.
        </EvidenceLine>
      </div>
    </div>
  )
}

function EvidenceLine({
  type,
  confidence,
  children,
}: {
  type: string
  confidence: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <span className="num text-[10.5px] text-[var(--fg-3)]">{type}</span>
        <span className="flex items-center gap-1.5">
          <span
            className="rounded-full px-1.5 py-0.5 text-[10px]"
            style={{ background: 'var(--win-soft)', color: 'var(--win)' }}
          >
            support
          </span>
          <span className="num text-[10.5px] text-[var(--fg-3)]">{confidence}</span>
        </span>
      </div>
      <p className="mt-1.5 text-[11.5px] leading-[1.55] text-[var(--fg-2)]">{children}</p>
    </div>
  )
}
