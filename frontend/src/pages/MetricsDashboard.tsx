import { useState } from 'react'
import { api, formatPercent, type EvalMetrics } from '../api/client'
import { Button, Metric, PageHeader, Progress, Surface } from '../components/ui'

/**
 * The last committed evaluation run, so the page says something on open rather than
 * showing an empty state until a one-minute job finishes. Labelled as a recorded run,
 * never as a live one. Same figures as README.md's results table.
 */
const REFERENCE = {
  working: { precision: 0.625, coverage: 0.214 },
  heldOut: { precision: 0.625, coverage: 0.215 },
  naive: { precision: 0.481, coverage: 0.423 },
}

/** The recorded run in full, so the page is populated before anyone clicks anything. */
const RECORDED: EvalMetrics = {
  precision: 0.625,
  recall: 0.625,
  f1: 0.625,
  coverage: 0.215,
  n_evaluated: 79,
  false_positive_cost_estimate_inr: 4500,
  confusion_matrix: { tp: 5, fp: 3, fn: 3, tn: 6, flagged_human: 62 },
}

export default function MetricsDashboard() {
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setRunning(true)
    setError(null)
    try {
      setMetrics(await api.evaluate())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  // Show the recorded run until a live one replaces it — never an empty page.
  const shown = metrics ?? RECORDED
  const cm = shown.confusion_matrix
  const isLive = metrics !== null

  return (
    <div className="space-y-5">
      <PageHeader
        title="Performance"
        sub="79 held-out disputes, never seen during tuning. Contest is the positive class."
        action={
          <Button variant="primary" onClick={run} disabled={running}>
            {running ? 'Running…' : metrics ? 'Run again' : 'Run evaluation'}
          </Button>
        }
      />

      {running && <Progress />}
      {error && <Surface className="p-4 text-[13px] text-[var(--risk)]">{error}</Surface>}

      {/* The headline claim: the tuned set and the unseen set agree. */}
      <Surface className="overflow-hidden">
        <div className="px-5 pb-1 pt-4">
          <h2 className="text-[13px]" style={{ fontVariationSettings: "'wght' 590" }}>
            Tuned set and unseen set agree
          </h2>
          <p className="mt-0.5 text-[12px] text-[var(--fg-3)]">
            Within a tenth of a point — the design generalised rather than fitting noise.
          </p>
        </div>
        <div className="grid gap-px sm:grid-cols-3" style={{ background: 'var(--line)' }}>
          <Compare label="Working set" sub="tuned against" {...REFERENCE.working} />
          <Compare label="Held-out" sub="never seen" {...REFERENCE.heldOut} highlight />
          <Compare label="Naive engine" sub="rejected" {...REFERENCE.naive} warn />
        </div>
        <p
          className="border-t px-5 py-3 text-[11.5px] leading-relaxed text-[var(--fg-3)]"
          style={{ borderColor: 'var(--line)' }}
        >
          Scoring evidence against the claim alone gave{' '}
          {formatPercent(REFERENCE.naive.precision)} — not weak but <em>inverted</em>,
          contesting losing cases more often than winning ones.
        </p>
      </Surface>

      <div className="rise space-y-5">
        <div className="flex items-center gap-2">
          <span
            className="size-1.5 rounded-full"
            style={{ background: isLive ? 'var(--win)' : 'var(--fg-3)' }}
          />
          <p className="text-[12px] text-[var(--fg-3)]">
            {isLive ? 'Live run, just now' : 'Last recorded run'}
          </p>
        </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric
              label="Precision"
              value={formatPercent(shown.precision)}
              sub={`right ${cm.tp} of ${cm.tp + cm.fp} contests`}
            />
            <Metric
              label="Recall"
              value={formatPercent(shown.recall)}
              sub={`caught ${cm.tp} of ${cm.tp + cm.fn} winnable`}
            />
            <Metric label="F1" value={formatPercent(shown.f1)} sub="the two balanced" />
            <Metric
              label="Coverage"
              value={formatPercent(shown.coverage)}
              sub={`calls ${shown.n_evaluated - cm.flagged_human} of ${shown.n_evaluated}`}
            />
          </div>

          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_16rem]">
            <Surface className="p-5">
              <h2 className="text-[13px]" style={{ fontVariationSettings: "'wght' 590" }}>
                Every case accounted for
              </h2>
              <table className="mt-3 w-full text-[13px]">
                <tbody>
                  <MatrixRow tone="win" cell="TP" n={cm.tp} meaning="Contested, and winnable" />
                  <MatrixRow tone="risk" cell="FP" n={cm.fp} meaning="Contested, and not — the costly error" />
                  <MatrixRow tone="warn" cell="FN" n={cm.fn} meaning="Conceded, but was winnable" />
                  <MatrixRow tone="fg-3" cell="TN" n={cm.tn} meaning="Conceded, correctly" />
                  <MatrixRow tone="accent" cell="—" n={cm.flagged_human} meaning="Handed to a person" />
                </tbody>
              </table>
            </Surface>

            <Surface className="p-5">
              <p className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
                Cost of being wrong
              </p>
              <p
                className="num mt-1.5 text-[27px] leading-none tracking-[-0.02em] text-[var(--warn)]"
                style={{ fontVariationSettings: "'wght' 560" }}
              >
                ₹
                {shown.false_positive_cost_estimate_inr.toLocaleString('en-IN', {
                  maximumFractionDigits: 0,
                })}
              </p>
              <p className="mt-2 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
                {cm.fp} lost contest{cm.fp === 1 ? '' : 's'} × ₹1,500. The number the design
                optimises against.
              </p>
            </Surface>
          </div>

          <p className="text-[11.5px] text-[var(--fg-3)]">
            Zero-shot, not fine-tuned. Ground truth is generated, not observed from real
            bank adjudications.
          </p>
      </div>
    </div>
  )
}

function Compare({
  label,
  sub,
  precision,
  coverage,
  highlight,
  warn,
}: {
  label: string
  sub: string
  precision: number
  coverage: number
  highlight?: boolean
  warn?: boolean
}) {
  return (
    <div
      className="p-4"
      style={{ background: highlight ? 'var(--surface-2)' : 'var(--surface)' }}
    >
      <p className="text-[12px]" style={{ fontVariationSettings: "'wght' 510" }}>
        {label}
      </p>
      <p className="text-[11px] text-[var(--fg-3)]">{sub}</p>
      <p
        className={`num mt-2 text-[27px] leading-none tracking-[-0.02em] ${warn ? 'text-[var(--risk)]' : ''}`}
        style={{ fontVariationSettings: "'wght' 560" }}
      >
        {formatPercent(precision)}
      </p>
      <p className="mt-1 text-[11px] text-[var(--fg-3)]">
        precision · {formatPercent(coverage)} coverage
      </p>
    </div>
  )
}

function MatrixRow({
  tone,
  cell,
  n,
  meaning,
}: {
  tone: string
  cell: string
  n: number
  meaning: string
}) {
  return (
    <tr>
      <td className="w-6 py-2">
        <span
          className="inline-block size-2 rounded-full"
          style={{ background: `var(--${tone})` }}
        />
      </td>
      <td className="num w-10 py-2 text-[11.5px] text-[var(--fg-3)]">{cell}</td>
      <td
        className="num w-12 py-2 text-[17px] tracking-[-0.02em]"
        style={{ fontVariationSettings: "'wght' 560" }}
      >
        {n}
      </td>
      <td className="py-2 text-[12px] text-[var(--fg-2)]">{meaning}</td>
    </tr>
  )
}
