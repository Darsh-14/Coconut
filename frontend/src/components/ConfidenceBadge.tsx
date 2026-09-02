import type { Recommendation, VerdictLabel } from '../api/client'
import { phaseCopy, RECOMMENDATIONS, statusLabel, VERDICTS } from '../lib/labels'
import { Badge, Meter } from './ui'
import { toneDot } from './uiTokens'

/** Section 12: support = green, contradict = red, neutral = grey. */
export function VerdictBadge({
  label,
  confidence,
}: {
  label: VerdictLabel
  confidence: number
}) {
  const v = VERDICTS[label]
  return (
    <span className="inline-flex items-center gap-2">
      <Badge tone={v.tone} dot>
        {v.label}
      </Badge>
      <span className="num text-[11.5px] text-[var(--fg-3)]">
        {(confidence * 100).toFixed(0)}%
      </span>
    </span>
  )
}

/** The headline verdict. The confidence rule is stated once, small, and not repeated. */
export function RecommendationBanner({
  recommendation,
  confidence,
  rationale,
}: {
  recommendation: Recommendation
  confidence: number
  rationale?: string | null
}) {
  const copy = RECOMMENDATIONS[recommendation]

  return (
    <section
      className="surface overflow-hidden"
      aria-label="Recommendation"
      style={{
        boxShadow: `var(--shadow-line), inset 2px 0 0 0 var(--${
          copy.tone === 'mute' ? 'fg-3' : copy.tone
        })`,
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-5 p-5">
        <div>
          <p className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
            Recommendation
          </p>
          <h2
            className="mt-1.5 flex items-center gap-2.5 text-[21px] tracking-[-0.022em]"
            style={{ fontVariationSettings: "'wght' 590" }}
          >
            <span className={`size-2 rounded-full ${toneDot(copy.tone)}`} />
            {copy.headline}
          </h2>
        </div>

        <div className="w-44">
          <div className="flex items-baseline justify-between">
            <span className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
              Confidence
            </span>
            <span
              className="num text-[17px] tracking-[-0.02em]"
              style={{ fontVariationSettings: "'wght' 560" }}
            >
              {(confidence * 100).toFixed(0)}%
            </span>
          </div>
          <div className="mt-1.5">
            <Meter value={confidence} tone={copy.tone} />
          </div>
          <p className="mt-1.5 text-[11px] text-[var(--fg-3)]">
            {recommendation === 'NO_ACTION_NEEDED'
              ? "NPCI's rule, not a model"
              : 'Weakest link, not average'}
          </p>
        </div>
      </div>

      {rationale && (
        <details className="group border-t" style={{ borderColor: 'var(--line)' }}>
          <summary className="cursor-pointer list-none px-5 py-2.5 text-[12px] text-[var(--fg-3)] transition hover:text-[var(--fg)]">
            Rule that fired
            <span className="ml-1.5 inline-block transition group-open:rotate-90">&rsaquo;</span>
          </summary>
          <p className="rise px-5 pb-4 text-[12.5px] leading-relaxed text-[var(--fg-2)]">
            {rationale}
          </p>
        </details>
      )}
    </section>
  )
}

export function PhaseBadge({ phase }: { phase: string }) {
  const copy = phaseCopy(phase)
  return <Badge title={copy.meaning}>{copy.label}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge>{statusLabel(status)}</Badge>
}
