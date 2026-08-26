import { useState } from 'react'
import { api, formatPercent, type EvalMetrics } from '../api/client'

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

  const cm = metrics?.confusion_matrix

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Evaluation</h1>
          <p className="mt-0.5 max-w-2xl text-sm text-slate-600">
            Runs the full pipeline over the held-out set, which is never used during
            development or tuning. CONTEST is the positive class.
          </p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={running}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {running ? 'Running…' : metrics ? 'Re-run evaluation' : 'Run evaluation'}
        </button>
      </header>

      {running && (
        <p className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
          Scoring every held-out record with the NLI model. This takes around a minute — it
          is real inference, not a cached number.
        </p>
      )}

      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}

      {!metrics && !running && (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-600">
          No results yet. Run the evaluation to compute metrics from the held-out set.
        </p>
      )}

      {metrics && cm && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Precision" value={formatPercent(metrics.precision)} />
            <StatCard label="Recall" value={formatPercent(metrics.recall)} />
            <StatCard label="F1" value={formatPercent(metrics.f1)} />
            <StatCard
              label="Coverage"
              value={formatPercent(metrics.coverage)}
              hint="auto-decided, not sent to a human"
            />
          </div>

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Confusion matrix</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Raw counts, unrounded. NEEDS_HUMAN_REVIEW records are excluded from
              precision/recall/F1 but counted in coverage.
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[34rem] text-sm">
                <tbody className="divide-y divide-slate-100">
                  <Row
                    cell="TP"
                    count={cm.tp}
                    meaning="model CONTEST, truth contest_win"
                    tone="text-green-700"
                  />
                  <Row
                    cell="FP"
                    count={cm.fp}
                    meaning="model CONTEST, truth contest_loss / should_accept"
                    tone="text-red-700"
                  />
                  <Row
                    cell="FN"
                    count={cm.fn}
                    meaning="model ACCEPT, truth contest_win"
                    tone="text-amber-700"
                  />
                  <Row
                    cell="TN"
                    count={cm.tn}
                    meaning="model ACCEPT, truth contest_loss / should_accept"
                    tone="text-slate-700"
                  />
                  <Row
                    cell="Human"
                    count={cm.flagged_human}
                    meaning="routed to a human instead of guessed"
                    tone="text-slate-700"
                  />
                </tbody>
              </table>
            </div>
          </section>

          <div className="grid gap-3 sm:grid-cols-2">
            <section className="rounded-lg border border-amber-200 bg-amber-50 p-4">
              <h2 className="text-xs font-medium uppercase tracking-wide text-amber-800">
                False-positive cost estimate
              </h2>
              <p className="mt-1 font-mono text-2xl font-semibold text-amber-900">
                ₹
                {metrics.false_positive_cost_estimate_inr.toLocaleString('en-IN', {
                  maximumFractionDigits: 0,
                })}
              </p>
              <p className="mt-1 text-xs text-amber-800">
                {cm.fp} false positive{cm.fp === 1 ? '' : 's'} × assumed representment cost.
                This is what guessing would have cost.
              </p>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-4">
              <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Records evaluated
              </h2>
              <p className="mt-1 font-mono text-2xl font-semibold text-slate-900">
                {metrics.n_evaluated}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                {metrics.n_evaluated - cm.flagged_human} auto-decided ·{' '}
                {cm.flagged_human} routed to a human
              </p>
            </section>
          </div>

          <p className="text-xs text-slate-500">
            The NLI model is used zero-shot and is not fine-tuned on dispute data. Coverage
            is deliberately low: the system declines to decide when the evidence does not
            resolve the claim, rather than guessing.
          </p>
        </>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 font-mono text-3xl font-semibold tabular-nums text-slate-900">
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

function Row({
  cell,
  count,
  meaning,
  tone,
}: {
  cell: string
  count: number
  meaning: string
  tone: string
}) {
  return (
    <tr>
      <td className={`py-2 pr-4 font-mono text-sm font-semibold ${tone}`}>{cell}</td>
      <td className="py-2 pr-4 font-mono text-lg tabular-nums">{count}</td>
      <td className="py-2 text-xs text-slate-600">{meaning}</td>
    </tr>
  )
}
