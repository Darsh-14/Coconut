import type { ClaimVerdict, EvidenceItem } from '../api/client'
import { evidenceLabel, VERDICTS } from '../lib/labels'
import { Meter } from './ui'
import { VerdictBadge } from './ConfidenceBadge'

/**
 * Evidence text with the model's highlighted span marked inline.
 *
 * The span is copied verbatim from the evidence by the verification engine, so a plain
 * substring match is exact rather than approximate. If it somehow does not match, the
 * text renders unchanged instead of silently dropping the highlight.
 */
function HighlightedText({ content, span }: { content: string; span: string | null }) {
  if (!span) return <>{content}</>
  const index = content.indexOf(span)
  if (index === -1) return <>{content}</>
  return (
    <>
      {content.slice(0, index)}
      <mark className="span">{span}</mark>
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
    <ol className="space-y-2.5">
      {evidence.map((item, index) => {
        const verdict = byIndex.get(index)
        const tone = verdict ? VERDICTS[verdict.label].tone : undefined

        return (
          <li
            key={index}
            className="surface p-4"
            // Colour appears here only to encode the verdict, never for decoration.
            style={
              tone && tone !== 'mute'
                ? { boxShadow: `var(--shadow-line), inset 2px 0 0 0 var(--${tone})` }
                : undefined
            }
          >
            <div>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span
                      className="text-[13px]"
                      style={{ fontVariationSettings: "'wght' 510" }}
                    >
                      {evidenceLabel(item.type)}
                    </span>
                    {item.source_ref && (
                      <code
                        className="num rounded bg-[var(--surface-2)] px-1.5 py-0.5 text-[11px] text-[var(--fg-3)]"
                        title="Cited in the representment"
                      >
                        {item.source_ref}
                      </code>
                    )}
                  </div>

                  {verdict ? (
                    <VerdictBadge label={verdict.label} confidence={verdict.confidence} />
                  ) : (
                    <span className="text-[11.5px] text-[var(--fg-3)]">not assessed</span>
                  )}
                </div>

                <p className="mt-2.5 text-[13px] leading-[1.65] text-[var(--fg-2)]">
                  <HighlightedText
                    content={item.content}
                    span={verdict?.highlighted_span ?? null}
                  />
                </p>

                {verdict && (
                  <div className="mt-3 flex items-center gap-3">
                    <div className="max-w-48 flex-1">
                      <Meter value={verdict.confidence} tone={VERDICTS[verdict.label].tone} />
                    </div>
                    {verdict.highlighted_span && (
                      <span className="text-[11px] text-[var(--fg-3)]">
                        Underlined text decided this
                      </span>
                    )}
                  </div>
                )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/** Counts above the list, so the shape of the bundle reads before the detail. */
export function EvidenceSummary({ verdicts }: { verdicts: ClaimVerdict[] }) {
  if (!verdicts.length) return null
  const n = (label: string) => verdicts.filter((v) => v.label === label).length
  const parts = [
    n('support') && `${n('support')} helping`,
    n('contradict') && `${n('contradict')} hurting`,
    n('neutral') && `${n('neutral')} neutral`,
  ].filter(Boolean)

  return <span className="text-[12px] text-[var(--fg-3)]">{parts.join(' · ')}</span>
}
