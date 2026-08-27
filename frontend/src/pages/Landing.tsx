import {
  ArrowRight,
  BookOpen,
  Boxes,
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
import { Link } from 'react-router-dom'
import { Mark, ThemeToggle } from '../components/ThemeToggle'
import { HEADLINE } from '../lib/headline'
import { paths } from '../lib/routes'
import { isSignedIn } from '../lib/session'

/**
 * The public front page.
 *
 * ARRANGEMENT
 * -----------
 * Modelled on razorpay.com's own section order, at the user's direction: sticky nav with
 * auth actions on the right, a hero whose subhead states breadth rather than a slogan, a
 * trust line immediately under it, a plain "what this is" explainer, grouped capability
 * card grids, a two-item spotlight for the genuinely novel work, a solutions table, a
 * developer section carrying a real curl sample, measured numbers, an FAQ, and a footer
 * with the legal/provenance details.
 *
 * Borrowed as structure only. None of Razorpay's brand, palette, copy or imagery is
 * reproduced — the page renders entirely in this product's own tokens, and every claim on
 * it is about this repo.
 *
 * WHY IT EXISTS
 * -------------
 * The dashboard opens on "₹10L at stake across 182 disputes" — precise and useful once you
 * know the product, meaningless before it. Someone arriving cold needs the thesis, the
 * guardrails and the measured numbers first.
 *
 * The limitations sit on the page rather than behind a link, deliberately. The argument
 * this project makes is that a dispute copilot which abstains on what it cannot settle
 * beats one that guesses confidently; a front page that oversold its own results would
 * undercut that argument on the way in.
 */
export default function Landing() {
  const entry = isSignedIn() ? paths.overview : paths.login

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg)' }}>
      <Nav entry={entry} />

      <main>
        {/* --- hero ---------------------------------------------------------------- */}
        <Band>
          <div className="grid gap-12 py-16 sm:py-24 lg:grid-cols-[1.15fr_1fr] lg:items-center">
            <div>
            <p
              className="text-[11.5px] tracking-[0.06em] text-[var(--fg-3)]"
              style={{ fontVariationSettings: "'wght' 540" }}
            >
              RAZORPAY AI BUILDATHON · TRACK 2 — AI RISK MANAGER
            </p>
            <h1
              className="mt-4 max-w-[19ch] text-[38px] leading-[1.06] tracking-[-0.035em] sm:text-[56px]"
              style={{ fontVariationSettings: "'wght' 620" }}
            >
              Chargeback defence that knows when it doesn&rsquo;t know.
            </h1>
            <p className="mt-5 max-w-[62ch] text-[15.5px] leading-relaxed text-[var(--fg-2)]">
              Recourse ingests a payment dispute, checks every piece of evidence against the
              specific claim the bank is making, recommends contest or accept with a
              confidence score and a full audit trail, drafts the representment, forecasts
              what India&rsquo;s UPI rails will do on their own — and when the evidence
              genuinely doesn&rsquo;t settle the question, says so instead of guessing.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                to={entry}
                className="pressable focus-ring inline-flex items-center gap-2 rounded-[var(--radius-control)] px-4 py-2.5 text-[13.5px]"
                style={{
                  background: 'var(--accent)',
                  color: 'var(--accent-fg)',
                  fontVariationSettings: "'wght' 550",
                }}
              >
                Open the dashboard
                <ArrowRight size={15} strokeWidth={2} aria-hidden="true" />
              </Link>
              <a
                href="#how"
                className="pressable focus-ring inline-flex items-center rounded-[var(--radius-control)] border px-4 py-2.5 text-[13.5px] text-[var(--fg-2)] transition hover:text-[var(--fg)]"
                style={{ borderColor: 'var(--line-strong)', fontVariationSettings: "'wght' 520" }}
              >
                How it works
              </a>
            </div>

            {/* Razorpay's "Used by 1,50,000+ businesses" slot. The honest equivalent here
                is not a customer count — it is the held-out measurement. */}
            <p className="mt-9 text-[12.5px] leading-relaxed text-[var(--fg-3)]">
              Evaluated on <span className="num text-[var(--fg-2)]">{HEADLINE.nEvaluated}</span>{' '}
              held-out disputes it had never seen —{' '}
              <span className="num text-[var(--fg-2)]">{HEADLINE.precision}</span> precision at{' '}
              <span className="num text-[var(--fg-2)]">{HEADLINE.coverage}</span> coverage, with
              the remainder deferred to a human rather than guessed.
            </p>
            </div>

            {/* Not an illustration. This is the product's own output for a case in the
                seeded set, carrying the same numbers as the curl sample further down --
                including the 0.50 overall confidence, which is the MINIMUM of the two
                verdicts rather than their average. */}
            <VerdictPreview />
          </div>
        </Band>

        {/* --- what it does -------------------------------------------------------- */}
        <Band tinted>
          <Section
            title="What Recourse does"
            sub="The whole loop, in one paragraph."
          >
            <div className="grid gap-8 lg:grid-cols-[1.35fr_1fr]">
              <div className="space-y-4 text-[13.5px] leading-relaxed text-[var(--fg-2)]">
                <p>
                  A merchant receives a chargeback. Contesting it costs roughly ₹1,500 in fees
                  and staff time, so below a certain ticket size merchants simply concede —
                  and when they do fight, they often fight cases they were always going to
                  lose, and pay twice.
                </p>
                <p>
                  <span className="text-[var(--fg)]" style={{ fontVariationSettings: "'wght' 560" }}>
                    So the expensive mistake is not failing to contest. It is contesting one
                    you were going to lose.
                  </span>{' '}
                  That reframes the objective: this system optimises precision on the cases it
                  decides and abstains on the rest, rather than maximising the number of
                  disputes it fights.
                </p>
                <p>
                  The hard part is that &ldquo;do we have delivery proof&rdquo; and &ldquo;do
                  we have <em>good</em> delivery proof&rdquo; look nearly identical to a
                  language model. A strong proof and a useless one both contradict
                  &ldquo;it never arrived&rdquo;. Closing that gap is the entire engineering
                  problem, and it is why the verification engine asks two questions per
                  evidence item rather than one.
                </p>
              </div>

              <ul className="space-y-3">
                {[
                  ['Decision made locally', 'An NLI cross-encoder, not an LLM call'],
                  ['Confidence is the minimum', 'Not the average — a chain is as strong as its weakest link'],
                  ['Threshold is calibrated', 'You name a risk budget; it derives the threshold'],
                  ['UPI rails modelled', 'NPCI caps and URCS auto-disposition, from the circulars'],
                  ['Every decision replayable', 'Persisted with the threshold that produced it'],
                  ['A human always approves', 'Nothing is ever submitted automatically'],
                ].map(([t, d]) => (
                  <li key={t} className="flex gap-2.5">
                    <span
                      className="mt-[6px] size-1.5 shrink-0 rounded-full"
                      style={{ background: 'var(--win)' }}
                    />
                    <span>
                      <span
                        className="block text-[13px]"
                        style={{ fontVariationSettings: "'wght' 550" }}
                      >
                        {t}
                      </span>
                      <span className="mt-0.5 block text-[12px] text-[var(--fg-3)]">{d}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </Section>
        </Band>

        {/* --- capabilities, grouped ------------------------------------------------ */}
        <Band id="how">
          <Section
            title={<>What&rsquo;s inside</>}
            sub="Grouped the way the pipeline actually runs."
          >
            <Group label="Decide">
              <Card
                icon={<Cpu size={16} strokeWidth={1.7} />}
                title="Verification engine"
                body="Two signals per evidence item — does it engage the claim, and does it substantiate a position specific enough to act on. Local, deterministic, free to run at evaluation scale."
              />
              <Card
                icon={<Scale size={16} strokeWidth={1.7} />}
                title="Decision aggregator"
                body="A plain readable conditional, not a model. Overall confidence is the minimum across the verdicts that drove the decision, never the average."
              />
              <Card
                icon={<Gauge size={16} strokeWidth={1.7} />}
                title="Conformal calibration"
                body="Thresholds are derived from a stated risk budget with a finite-sample bound, rather than picked by hand and defended after the fact."
              />
              <Card
                icon={<FileSearch size={16} strokeWidth={1.7} />}
                title="Span-level explainability"
                body="The sentence inside each evidence item that actually drove its verdict, highlighted inline — so a merchant can see why, not just what."
              />
            </Group>

            <Group label="India-native rails" cols={3}>
              <Card
                icon={<Landmark size={16} strokeWidth={1.7} />}
                title="URCS disposition forecast"
                body="Predicts whether NPCI's system will auto-reject a UPI dispute before it ever reaches the merchant, and under which code."
              />
              <Card
                icon={<Wallet size={16} strokeWidth={1.7} />}
                title="Dispute budget counters"
                body="Rolling 30-day counts against the 10-per-customer and 5-per-payer-payee caps, shown as a budget the payer is spending down."
              />
              <Card
                icon={<ShieldCheck size={16} strokeWidth={1.7} />}
                title="Dated rule provenance"
                body="Every cap and code lives in one config block carrying the date it was verified against NPCI's circulars. That date is on screen, not buried."
              />
            </Group>

            <Group label="Operate">
              <Card
                icon={<ListChecks size={16} strokeWidth={1.7} />}
                title="Dispute queue"
                body="Deadline countdowns, rail badges, recommendation split, and cases URCS will resolve on their own visually de-prioritised."
              />
              <Card
                icon={<PenLine size={16} strokeWidth={1.7} />}
                title="Representment drafting"
                body="Provider-pluggable prose generation that rewrites a decision the engine already made. It cannot change a verdict, a recommendation or a confidence."
              />
              <Card
                icon={<ClipboardCheck size={16} strokeWidth={1.7} />}
                title="Audit trail"
                body="Every decision, approval, edit and withdrawal, with the exact payload that would have gone to Razorpay stored beside it and labelled as not sent."
              />
              <Card
                icon={<Radio size={16} strokeWidth={1.7} />}
                title="Signed webhook intake"
                body="Razorpay events verified against the raw request body before parsing. Fails closed with no secret configured, and never ingests dispute events."
              />
            </Group>
          </Section>
        </Band>

        {/* --- spotlight ------------------------------------------------------------ */}
        <Band tinted>
          <Section
            title="The two things nobody else builds"
            sub="Checked against Justt, Chargeflow, Riskified, Kount and Shopify's own dispute tooling."
          >
            <div className="grid gap-4 lg:grid-cols-2">
              <Spotlight
                icon={<Gauge size={18} strokeWidth={1.7} />}
                eyebrow="METHODOLOGICAL"
                title="Name a risk budget, not a threshold"
                body="Tell the system the maximum false-positive rate you will tolerate on disputes it contests automatically. It calibrates its own confidence threshold against a held-out calibration split using conformal risk control, then reports what that budget costs you in coverage — or tells you the budget is not achievable on this data rather than quietly falling back to a default."
                note="Conformal risk control is established in drug discovery and medical AI. As far as I can find, nobody has applied it to payment disputes."
              />
              <Spotlight
                icon={<Landmark size={18} strokeWidth={1.7} />}
                eyebrow="DOMAIN"
                title="UPI outcomes are deterministic, so predict them exactly"
                body="Every commercial chargeback product is architected around Visa and Mastercard mechanics, because that is where their market is. UPI does not work that way: NPCI caps disputes at 10 per customer and 5 per payer-payee per 30 days, and URCS auto-rejects the overflow under CD1 and CD2 with no human ever looking. Recourse forecasts that from the rules and tells the merchant to spend nothing."
                note="It is a rules engine, not a model — which is exactly why it is fully explainable and why the rules carry a verification date."
              />
            </div>
          </Section>
        </Band>

        {/* --- outcomes table ------------------------------------------------------- */}
        <Band>
          <Section
            title="Where a case can land"
            sub="Four outcomes, each with a rule you can read."
          >
            <div className="surface overflow-x-auto">
              <table className="w-full min-w-[46rem] text-left text-[12.5px]">
                <thead
                  className="border-b text-[11px] tracking-[0.03em] text-[var(--fg-3)]"
                  style={{ borderColor: 'var(--line)' }}
                >
                  <tr>
                    <th className="px-4 py-3 font-normal">Outcome</th>
                    <th className="px-4 py-3 font-normal">What triggers it</th>
                    <th className="px-4 py-3 font-normal">What the merchant does</th>
                  </tr>
                </thead>
                <tbody className="divide-y" style={{ borderColor: 'var(--line)' }}>
                  <Row
                    tone="var(--win)"
                    name="CONTEST"
                    trigger="Every verdict supports, confidence clears the calibrated threshold, and at least two distinct evidence types back it."
                    action="Review the drafted representment, edit it, approve it."
                  />
                  <Row
                    tone="var(--risk)"
                    name="ACCEPT"
                    trigger="Some evidence item contradicts the merchant's own position at or above the calibrated threshold."
                    action="Concede. Spending the representment fee here loses twice."
                  />
                  <Row
                    tone="var(--warn)"
                    name="NEEDS_HUMAN_REVIEW"
                    trigger="Anything else — including the case where the requested risk budget is not achievable at all."
                    action="A person decides. This is roughly seven cases in ten, by design."
                  />
                  <Row
                    tone="var(--fg-3)"
                    name="NO_ACTION_NEEDED"
                    trigger="URCS is forecast to auto-reject the dispute under CD1 or CD2 before it reaches the merchant."
                    action="Nothing. The rails resolve it without you."
                  />
                </tbody>
              </table>
            </div>
          </Section>
        </Band>

        {/* --- developers ----------------------------------------------------------- */}
        <Band tinted id="developers">
          <Section
            title="For developers"
            sub="Every screen in the dashboard is this API and nothing else."
          >
            <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
              <div>
                <ul className="space-y-2">
                  {[
                    ['GET', '/disputes', 'the queue, with search and paging'],
                    ['GET', '/disputes/{id}', 'full case, decision and audit trail'],
                    ['POST', '/disputes/{id}/decide', 'run the engine, persist a Decision'],
                    ['POST', '/disputes/{id}/approve', 'human approval; builds the payload'],
                    ['GET', '/disputes/{id}/urcs-forecast', 'NPCI cap forecast for UPI rails'],
                    ['POST', '/calibrate', 'derive a threshold from a risk budget'],
                    ['GET', '/verify-guarantee', 'check the budget held on the test split'],
                    ['POST', '/evaluate', 'held-out precision, recall, F1, coverage'],
                  ].map(([m, p, d]) => (
                    <li key={p} className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
                      <span
                        className="num shrink-0 text-[10.5px]"
                        style={{ color: m === 'GET' ? 'var(--win)' : 'var(--accent)' }}
                      >
                        {m}
                      </span>
                      <code className="num text-[12px] text-[var(--fg)]">{p}</code>
                      <span className="text-[11.5px] text-[var(--fg-3)]">{d}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-5 text-[12px] leading-relaxed text-[var(--fg-3)]">
                  Interactive reference at <code className="num">/api/docs</code> when the
                  server is running. Schemas are Pydantic v2 and the frontend types mirror
                  them one to one.
                </p>
              </div>

              <div>
                <div
                  className="overflow-x-auto rounded-[var(--radius-card)] border p-4"
                  style={{ borderColor: 'var(--line)', background: 'var(--surface-solid)' }}
                >
                  <pre className="num text-[11.5px] leading-relaxed text-[var(--fg-2)]">
{`# decide a case, then read back what it concluded
curl -X POST http://localhost:8000/disputes/disp_synthetic_0168/decide

{
  "dispute_id": "disp_synthetic_0168",
  "recommendation": "CONTEST",
  "confidence": 0.50,
  "calibrated_threshold_used": 0.72,
  "claim_verdicts": [
    {
      "evidence_index": 0,
      "label": "support",
      "confidence": 0.50,
      "highlighted_span": "OTP captured at delivery, ID
                           matching the KYC record"
    }
  ],
  "model_version": "cross-encoder/nli-deberta-v3-base"
}`}
                  </pre>
                </div>
                <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
                  Note <code className="num">calibrated_threshold_used</code>: a decision is
                  only reproducible if you know which threshold produced it, so it is
                  persisted with the decision rather than inferred later.
                </p>
              </div>
            </div>
          </Section>
        </Band>

        {/* --- measured ------------------------------------------------------------- */}
        <Band>
          <Section
            title="Measured, on data it had never seen"
            sub={`${HEADLINE.nEvaluated} held-out records, untouched during development · run ${HEADLINE.measuredOn}`}
          >
            <div className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-4">
              <Figure value={HEADLINE.precision} label="precision" tone="var(--win)" />
              <Figure value={HEADLINE.recall} label="recall" />
              <Figure value={HEADLINE.f1} label="F1" />
              <Figure
                value={HEADLINE.coverage}
                label="coverage — the rest defers to a human"
                tone="var(--warn)"
              />
            </div>

            <div className="mt-10 grid gap-6 lg:grid-cols-[1fr_1.2fr]">
              <div className="surface overflow-x-auto">
                <table className="w-full text-left text-[12.5px]">
                  <tbody className="divide-y" style={{ borderColor: 'var(--line)' }}>
                    {[
                      ['TP', 9, 'model CONTEST, truth contest_win'],
                      ['FP', 4, 'model CONTEST, truth loss / should accept'],
                      ['FN', 3, 'model ACCEPT, truth contest_win'],
                      ['TN', 7, 'model ACCEPT, truth loss / should accept'],
                      ['Human', 51, 'routed to a person instead of guessed'],
                      ['URCS', 5, 'over an NPCI cap — excluded from precision'],
                    ].map(([k, n, d]) => (
                      <tr key={String(k)}>
                        <td className="num px-4 py-2.5 text-[var(--fg-3)]">{k}</td>
                        <td className="num px-2 py-2.5 text-[var(--fg)]">{n}</td>
                        <td className="px-4 py-2.5 text-[11.5px] text-[var(--fg-3)]">{d}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="space-y-4 text-[13px] leading-relaxed text-[var(--fg-2)]">
                <p>
                  Coverage of{' '}
                  <span className="num">{HEADLINE.coverage}</span> means Recourse declines to
                  decide on roughly seven cases in ten. That is the product, not a shortfall
                  — a copilot that says &ldquo;I don&rsquo;t know&rdquo; on the cases it
                  cannot settle, and is right on roughly seven of every ten it does decide, is more useful
                  than one that guesses confidently on everything.
                </p>
                <p>
                  <span className="text-[var(--fg)]" style={{ fontVariationSettings: "'wght' 560" }}>
                    The number that actually validates the work is not the precision.
                  </span>{' '}
                  It is that every threshold was tuned on the working set, the held-out set
                  was opened once at the end, and the two scored within a whisker of each
                  other. It generalised rather than fitting noise. The naive single-signal
                  version of the same engine scored <span className="num">0.481</span> —
                  worse than a coin flip, and inverted.
                </p>
                <p className="text-[12px] text-[var(--fg-3)]">
                  False-positive cost estimate at this operating point: ₹
                  {HEADLINE.falsePositiveCostInr.toLocaleString('en-IN')}.
                </p>
              </div>
            </div>
          </Section>
        </Band>

        {/* --- faq ------------------------------------------------------------------ */}
        <Band tinted id="faq">
          <Section title="Questions you should ask" sub="Answered plainly, including the awkward ones.">
            <div className="grid gap-x-10 lg:grid-cols-2">
              <Faq q="Are these real Razorpay disputes?">
                No, and the distinction is kept sharp everywhere in the code. Razorpay&rsquo;s
                test mode has no mechanism to fabricate a chargeback on demand, so there is no
                real disputable transaction to build against. The dispute records — claim
                text, evidence bundle, ground-truth label — are generated. The{' '}
                <code className="num">payment_id</code> underneath a dispute <em>can</em> be a
                real test-mode Razorpay payment, and committed records are.
              </Faq>
              <Faq q="Does it ever submit anything to Razorpay or a bank?">
                Never, and it cannot be configured to. On approval it builds the exact payload
                it would send, stores it in the audit log labelled &ldquo;would submit to
                Razorpay&rdquo;, and stops. That is enforced in two independent places, both
                covered by tests that fail loudly if either regresses.
              </Faq>
              <Faq q="Why not use an LLM to make the decision?">
                Cost, determinism and auditability. The decision runs a local NLI
                cross-encoder: reproducible by anyone who clones the repo, free to run
                thousands of times during evaluation, no rate limits, same answer every time.
                A language model only rewrites prose after the verdict already exists, and
                cannot alter a recommendation, a verdict or a confidence.
              </Faq>
              <Faq q="Is the sign-in screen real authentication?">
                No, deliberately. This is a single-merchant demo, so an account system would
                be scope without signal — and a reviewer meeting a credential wall with no
                credentials is worse than no sign-in at all. Any credentials continue, nothing
                is checked or stored, and no API route is protected by it. The sign-in card
                says so itself.
              </Faq>
              <Faq q="What does the conformal guarantee actually promise?">
                That with probability at least 1&nbsp;&minus;&nbsp;δ over the draw of the
                calibration set, the false-positive rate among disputes auto-contested is at
                most α — assuming calibration and deployment data are exchangeable. Nothing
                more. It says nothing about recall or money recovered.
              </Faq>
              <Faq q="What did calibration reveal that you would rather it hadn't?">
                That the tightest budget this data supports is around 72%, which is not a
                useful promise. The method is correct; the confidence score underneath it has
                too little dynamic range for a threshold to bite on — the same ceiling found
                three separate ways. Calibration did not fix the model. It made the
                model&rsquo;s limits impossible to hide, and still beat hand-picked thresholds
                out of sample.
              </Faq>
            </div>
          </Section>
        </Band>

        {/* --- cta ------------------------------------------------------------------ */}
        <Band>
          <div className="py-16 text-center">
            <h2
              className="text-[26px] tracking-[-0.03em]"
              style={{ fontVariationSettings: "'wght' 600" }}
            >
              See it decide a real case.
            </h2>
            <p className="mx-auto mt-3 max-w-[46ch] text-[13.5px] leading-relaxed text-[var(--fg-2)]">
              182 disputes are seeded and waiting. Open one, watch it verify each piece of
              evidence against the claim, and approve a representment it drafted.
            </p>
            <Link
              to={entry}
              className="pressable focus-ring mt-7 inline-flex items-center gap-2 rounded-[var(--radius-control)] px-5 py-3 text-[14px]"
              style={{
                background: 'var(--accent)',
                color: 'var(--accent-fg)',
                fontVariationSettings: "'wght' 550",
              }}
            >
              Open the dashboard
              <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
            </Link>
          </div>
        </Band>
      </main>

      <Footer entry={entry} />
    </div>
  )
}

/* -- layout ------------------------------------------------------------------------ */

function Nav({ entry }: { entry: string }) {
  return (
    <header className="material sticky top-0 z-30 border-b" style={{ borderColor: 'var(--line)' }}>
      <div className="mx-auto flex max-w-[72rem] items-center justify-between gap-4 px-5 py-3 sm:px-8">
        <div className="flex items-center gap-2.5">
          <Mark size={28} />
          <span
            className="text-[14.5px] tracking-[-0.02em]"
            style={{ fontVariationSettings: "'wght' 600" }}
          >
            Recourse
          </span>
        </div>

        <nav className="hidden items-center gap-1 md:flex">
          <NavAnchor href="#how">How it works</NavAnchor>
          <NavAnchor href="#developers">Developers</NavAnchor>
          <NavAnchor href="#faq">FAQ</NavAnchor>
        </nav>

        <div className="flex items-center gap-1.5">
          <ThemeToggle compact />
          <Link
            to={paths.login}
            className="pressable focus-ring hidden rounded-[var(--radius-control)] px-3 py-1.5 text-[13px] text-[var(--fg-2)] transition hover:text-[var(--fg)] sm:inline-flex"
            style={{ fontVariationSettings: "'wght' 520" }}
          >
            Sign in
          </Link>
          <Link
            to={entry}
            className="pressable focus-ring rounded-[var(--radius-control)] px-3.5 py-1.5 text-[13px]"
            style={{
              background: 'var(--fg)',
              color: 'var(--bg)',
              fontVariationSettings: "'wght' 540",
            }}
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
      className="focus-ring rounded-[var(--radius-control)] px-2.5 py-1.5 text-[13px] text-[var(--fg-2)] transition hover:text-[var(--fg)]"
      style={{ fontVariationSettings: "'wght' 510" }}
    >
      {children}
    </a>
  )
}

/** A full-bleed band so alternating sections read as distinct slabs, as on razorpay.com. */
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
      className={id ? 'scroll-mt-16 border-t' : 'border-t'}
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
    <section className="py-14 sm:py-18">
      <h2
        className="text-[21px] tracking-[-0.025em]"
        style={{ fontVariationSettings: "'wght' 600" }}
      >
        {title}
      </h2>
      {sub && <p className="mt-1.5 text-[13px] text-[var(--fg-3)]">{sub}</p>}
      <div className="mt-8">{children}</div>
    </section>
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
    <div className="mb-9 last:mb-0">
      <h3
        className="mb-3 flex items-center gap-2 text-[11px] tracking-[0.05em] text-[var(--fg-3)]"
        style={{ fontVariationSettings: "'wght' 560" }}
      >
        <Boxes size={13} strokeWidth={1.7} aria-hidden="true" />
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

/* -- pieces ------------------------------------------------------------------------ */

function Card({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode
  title: string
  body: string
}) {
  return (
    <div className="surface p-4">
      <span className="text-[var(--fg-2)]">{icon}</span>
      <h4 className="mt-2.5 text-[13px] tracking-[-0.01em]" style={{ fontVariationSettings: "'wght' 560" }}>
        {title}
      </h4>
      <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--fg-3)]">{body}</p>
    </div>
  )
}

function Spotlight({
  icon,
  eyebrow,
  title,
  body,
  note,
}: {
  icon: React.ReactNode
  eyebrow: string
  title: string
  body: string
  note: string
}) {
  return (
    <div className="surface flex flex-col p-6">
      <div className="flex items-center gap-2.5">
        <span className="text-[var(--accent)]">{icon}</span>
        <span
          className="text-[10.5px] tracking-[0.06em] text-[var(--fg-3)]"
          style={{ fontVariationSettings: "'wght' 560" }}
        >
          {eyebrow}
        </span>
      </div>
      <h3
        className="mt-3.5 text-[16px] leading-snug tracking-[-0.02em]"
        style={{ fontVariationSettings: "'wght' 580" }}
      >
        {title}
      </h3>
      <p className="mt-2.5 flex-1 text-[12.5px] leading-relaxed text-[var(--fg-2)]">{body}</p>
      <p
        className="mt-4 border-t pt-3.5 text-[12px] leading-relaxed text-[var(--fg-3)]"
        style={{ borderColor: 'var(--line)' }}
      >
        {note}
      </p>
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
          <span className="num text-[11.5px]" style={{ color: tone }}>
            {name}
          </span>
        </span>
      </td>
      <td className="px-4 py-3.5 align-top text-[var(--fg-2)]">{trigger}</td>
      <td className="px-4 py-3.5 align-top text-[var(--fg-3)]">{action}</td>
    </tr>
  )
}

function Figure({ value, label, tone }: { value: string; label: string; tone?: string }) {
  return (
    <div>
      <div
        className="num text-[34px] leading-none tracking-[-0.03em]"
        style={{ color: tone ?? 'var(--fg)', fontVariationSettings: "'wght' 560" }}
      >
        {value}
      </div>
      <div className="mt-2 text-[12px] leading-snug text-[var(--fg-3)]">{label}</div>
    </div>
  )
}

/**
 * The hero's right column: one seeded case rendered in the same visual language the case
 * page itself uses — verdict badges, a confidence meter, and the highlighted span that
 * drove the verdict.
 *
 * Static, and deliberately consistent: every value here matches the curl sample in the
 * developer section, so nothing on this page contradicts anything else on it. Note the
 * overall 0.50 — the minimum of the two verdicts, not their average. Showing that on the
 * front page makes the rule visible before anyone reads a word about it.
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

      <div className="border-b px-4 py-3.5" style={{ borderColor: 'var(--line)' }}>
        <div className="flex items-baseline justify-between gap-3">
          <span className="flex items-center gap-2">
            <span className="size-1.5 rounded-full" style={{ background: 'var(--win)' }} />
            <span className="num text-[12px]" style={{ color: 'var(--win)' }}>
              CONTEST
            </span>
          </span>
          <span className="num text-[11.5px] text-[var(--fg-3)]">confidence 0.50</span>
        </div>
        <div
          className="mt-2.5 h-1 overflow-hidden rounded-full"
          style={{ background: 'var(--surface-3)' }}
        >
          <div className="h-full rounded-full" style={{ width: '50%', background: 'var(--win)' }} />
        </div>
        <p className="mt-2 text-[10.5px] leading-snug text-[var(--fg-3)]">
          the minimum across the driving verdicts, not their average
        </p>
      </div>

      <div className="border-b px-4 py-3" style={{ borderColor: 'var(--line)' }}>
        <p
          className="text-[10px] tracking-[0.05em] text-[var(--fg-3)]"
          style={{ fontVariationSettings: "'wght' 560" }}
        >
          BANK&rsquo;S CLAIM
        </p>
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--fg-2)]">
          Cardholder states the goods were never received and the merchant has not provided
          proof of delivery.
        </p>
      </div>

      <div className="space-y-4 p-4">
        <EvidenceLine type="delivery_proof" confidence="0.90">
          Courier proof of delivery signed at 14:22.{' '}
          <mark
            className="rounded px-1"
            style={{ background: 'var(--warn-soft)', color: 'var(--fg)' }}
          >
            OTP captured at delivery, ID matching the KYC record
          </mark>
          {'.'}
        </EvidenceLine>
        <EvidenceLine type="order_history" confidence="0.50">
          Three prior orders to the same address in the past year, none disputed.
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
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-[var(--fg-2)]">{children}</p>
    </div>
  )
}

/**
 * Native details/summary rather than a JS accordion: keyboard operable, announced
 * correctly by screen readers, and open-by-default if the browser prints the page.
 */
function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <details className="group border-b py-4" style={{ borderColor: 'var(--line)' }}>
      <summary
        className="focus-ring flex cursor-pointer list-none items-start justify-between gap-4 rounded text-[13.5px] leading-snug"
        style={{ fontVariationSettings: "'wght' 550" }}
      >
        {q}
        <span
          className="mt-0.5 shrink-0 text-[var(--fg-3)] transition-transform duration-200 group-open:rotate-45"
          aria-hidden="true"
        >
          +
        </span>
      </summary>
      <p className="mt-2.5 text-[12.5px] leading-relaxed text-[var(--fg-2)]">{children}</p>
    </details>
  )
}

function Footer({ entry }: { entry: string }) {
  return (
    <footer className="border-t" style={{ borderColor: 'var(--line)' }}>
      <div className="mx-auto max-w-[72rem] px-5 py-10 sm:px-8">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <div className="flex items-center gap-2.5">
              <Mark size={26} />
              <span className="text-[13.5px]" style={{ fontVariationSettings: "'wght' 580" }}>
                Recourse
              </span>
            </div>
            <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
              Explainable chargeback defence. Built for Razorpay&rsquo;s AI Buildathon,
              Track 2.
            </p>
          </div>

          <FooterCol
            title="Product"
            items={[
              ['How it works', '#how'],
              ['Developers', '#developers'],
              ['FAQ', '#faq'],
            ]}
          />

          <div>
            <h3
              className="text-[11px] tracking-[0.05em] text-[var(--fg-3)]"
              style={{ fontVariationSettings: "'wght' 560" }}
            >
              STACK
            </h3>
            <ul className="mt-3 space-y-1.5 text-[11.5px] text-[var(--fg-3)]">
              <li>FastAPI · Pydantic v2 · SQLAlchemy</li>
              <li>cross-encoder/nli-deberta-v3-base</li>
              <li>React · TypeScript · Vite · Tailwind</li>
              <li>razorpay (test mode only)</li>
            </ul>
          </div>

          <div>
            <h3
              className="text-[11px] tracking-[0.05em] text-[var(--fg-3)]"
              style={{ fontVariationSettings: "'wght' 560" }}
            >
              GUARDRAILS
            </h3>
            <ul className="mt-3 space-y-1.5 text-[11.5px] text-[var(--fg-3)]">
              {[
                ['Test-mode keys enforced at startup', 'var(--win)'],
                ['Dispute records are synthetic', 'var(--fg-3)'],
                ['Never auto-submits to Razorpay', 'var(--warn)'],
                ['Defence only — no offensive action', 'var(--win)'],
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
          className="mt-9 flex flex-wrap items-center justify-between gap-3 border-t pt-5 text-[11.5px] text-[var(--fg-3)]"
          style={{ borderColor: 'var(--line)' }}
        >
          <span className="flex items-center gap-2">
            <BookOpen size={13} strokeWidth={1.7} aria-hidden="true" />
            Dispute data is synthetic; backing payments are real test-mode Razorpay payments.
          </span>
          <Link
            to={entry}
            className="focus-ring inline-flex items-center gap-1.5 rounded transition hover:text-[var(--fg)]"
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
      <h3
        className="text-[11px] tracking-[0.05em] text-[var(--fg-3)]"
        style={{ fontVariationSettings: "'wght' 560" }}
      >
        {title.toUpperCase()}
      </h3>
      <ul className="mt-3 space-y-1.5">
        {items.map(([label, href]) => (
          <li key={label}>
            <a
              href={href}
              className="focus-ring rounded text-[11.5px] text-[var(--fg-3)] transition hover:text-[var(--fg)]"
            >
              {label}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

