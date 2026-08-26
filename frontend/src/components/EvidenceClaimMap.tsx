import type { ClaimVerdict, EvidenceItem } from '../api/client'
import { VerdictBadge } from './ConfidenceBadge'

const TYPE_LABELS: Record<string, string> = {
  delivery_proof: 'Delivery proof',
  communication_log: 'Communication log',
  device_signal: 'Device signal',
  order_history: 'Order history',
  other: 'Other',
}

/**
 * Render evidence text with the model's highlighted span marked inline.
 *
 * The span is copied verbatim from the evidence by the verification engine, so a plain
 * substring match is exact rather than approximate. If it somehow does not match, the
 * text is rendered unchanged instead of dropping the highlight silently.
 */
function HighlightedText({ content, span }: { content: string; span: string | null }) {
  if (!span) return <>{content}</>

  const index = content.indexOf(span)
  if (index === -1) return <>{content}</>

  return (
    <>
      {content.slice(0, index)}
      <mark className="rounded bg-yellow-200/70 px-0.5 py-0.5 font-medium text-slate-900">
        {span}
      </mark>
      {content.slice(index + span.length)}
    </>
  )
}

export function EvidenceClaimMap({
  evidence,
  verdicts,
}: {
  evidence: EvidenceItem[]
  verdicts: ClaimVerdict[]
}) {
  const byIndex = new Map(verdicts.map((v) => [v.evidence_index, v]))

  return (
    <ol className="space-y-3">
      {evidence.map((item, index) => {
        const verdict = byIndex.get(index)
        return (
          <li
            key={index}
            className="rounded-lg border border-slate-200 bg-white p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-slate-500">#{index + 1}</span>
                <span className="text-sm font-medium text-slate-900">
                  {TYPE_LABELS[item.type] ?? item.type}
                </span>
                {item.source_ref && (
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    {item.source_ref}
                  </code>
                )}
              </div>
              {verdict ? (
                <VerdictBadge label={verdict.label} confidence={verdict.confidence} />
              ) : (
                <span className="text-xs text-slate-400">not yet assessed</span>
              )}
            </div>

            <p className="mt-2 text-sm leading-relaxed text-slate-700">
              <HighlightedText
                content={item.content}
                span={verdict?.highlighted_span ?? null}
              />
            </p>

            {verdict?.highlighted_span && (
              <p className="mt-2 text-xs text-slate-500">
                Highlighted: the sentence that most drove this verdict.
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
