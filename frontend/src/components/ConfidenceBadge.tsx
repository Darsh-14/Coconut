import type { Recommendation, VerdictLabel } from '../api/client'

/** Section 12: support = green, contradict = red, neutral = gray. */
const VERDICT_STYLES: Record<VerdictLabel, string> = {
  support: 'bg-green-100 text-green-800 ring-green-600/20',
  contradict: 'bg-red-100 text-red-800 ring-red-600/20',
  neutral: 'bg-slate-100 text-slate-700 ring-slate-500/20',
}

const VERDICT_LABELS: Record<VerdictLabel, string> = {
  support: 'Supports contesting',
  contradict: 'Contradicts merchant',
  neutral: 'Does not resolve',
}

export function VerdictBadge({
  label,
  confidence,
}: {
  label: VerdictLabel
  confidence: number
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${VERDICT_STYLES[label]}`}
    >
      {VERDICT_LABELS[label]}
      <span className="font-mono tabular-nums opacity-75">
        {(confidence * 100).toFixed(0)}%
      </span>
    </span>
  )
}

const RECOMMENDATION_STYLES: Record<Recommendation, string> = {
  CONTEST: 'border-green-300 bg-green-50 text-green-900',
  ACCEPT: 'border-amber-300 bg-amber-50 text-amber-900',
  NEEDS_HUMAN_REVIEW: 'border-slate-300 bg-slate-50 text-slate-900',
}

const RECOMMENDATION_COPY: Record<Recommendation, string> = {
  CONTEST: 'The evidence supports contesting this dispute.',
  ACCEPT: 'The evidence undermines the merchant. Contesting would likely fail.',
  NEEDS_HUMAN_REVIEW:
    'The evidence does not resolve this claim either way. Recourse is not guessing.',
}

export function RecommendationBanner({
  recommendation,
  confidence,
  rationale,
}: {
  recommendation: Recommendation
  confidence: number
  rationale?: string | null
}) {
  return (
    <section
      className={`rounded-lg border p-4 ${RECOMMENDATION_STYLES[recommendation]}`}
      aria-label="Recommendation"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold tracking-tight">
          {recommendation.replace(/_/g, ' ')}
        </h2>
        <p className="text-sm">
          Overall confidence{' '}
          <span className="font-mono font-semibold tabular-nums">
            {(confidence * 100).toFixed(1)}%
          </span>
          <span className="ml-1 opacity-70">(weakest link)</span>
        </p>
      </div>
      <p className="mt-1 text-sm">{RECOMMENDATION_COPY[recommendation]}</p>
      {rationale && <p className="mt-2 text-sm opacity-80">{rationale}</p>}
    </section>
  )
}

const PHASE_STYLES: Record<string, string> = {
  fraud: 'bg-red-50 text-red-700 ring-red-600/20',
  retrieval: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  chargeback: 'bg-violet-50 text-violet-700 ring-violet-600/20',
  pre_arbitration: 'bg-orange-50 text-orange-700 ring-orange-600/20',
  arbitration: 'bg-rose-50 text-rose-700 ring-rose-600/20',
}

export function PhaseBadge({ phase }: { phase: string }) {
  const style = PHASE_STYLES[phase] ?? 'bg-slate-50 text-slate-700 ring-slate-500/20'
  return (
    <span
      className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {phase.replace(/_/g, ' ')}
    </span>
  )
}

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-700',
  decided: 'bg-blue-100 text-blue-800',
  approved: 'bg-green-100 text-green-800',
  submitted: 'bg-emerald-100 text-emerald-900',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? 'bg-slate-100 text-slate-700'
      }`}
    >
      {status}
    </span>
  )
}
