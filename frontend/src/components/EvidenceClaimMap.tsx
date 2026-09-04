import { useState } from 'react'
import { api, type ClaimVerdict, type EvidenceItem, type EvidenceType } from '../api/client'
import { EvidenceDocumentViewer } from './EvidenceDocumentViewer'
import { evidenceLabel, VERDICTS } from '../lib/labels'
import { Button, Meter } from './ui'
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
  disputeId,
  evidence,
  verdicts,
  stale = false,
  onChanged,
}: {
  disputeId: string
  evidence: EvidenceItem[]
  verdicts: ClaimVerdict[]
  /** Evidence moved since these verdicts were computed, so they no longer line up. */
  stale?: boolean
  onChanged?: () => void
}) {
  // A ClaimVerdict joins to evidence by INDEX. Once the bundle has changed, drawing the
  // old verdicts against the new list would put a verdict about one item onto another —
  // most misleadingly right after a merchant adds the evidence they expect to win on. So
  // when stale the badges are withheld rather than guessed.
  const byIndex = new Map(stale ? [] : verdicts.map((v) => [v.evidence_index, v] as const))

  // Which record is open, by bundle index. null = none.
  const [openIndex, setOpenIndex] = useState<number | null>(null)
  const [removing, setRemoving] = useState<number | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  async function remove(index: number) {
    setRemoving(index)
    setRemoveError(null)
    try {
      await api.removeEvidence(disputeId, index)
      onChanged?.()
    } catch (error) {
      setRemoveError(`Could not remove evidence: ${(error as Error).message}`)
    } finally {
      setRemoving(null)
    }
  }

  return (
    <>
      {removeError && (
        <p className="mb-2.5 text-[11.5px] text-[var(--risk)]" role="alert">
          {removeError}
        </p>
      )}
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
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="text-[13px]" style={{ fontVariationSettings: "'wght' 510" }}>
                    {evidenceLabel(item.type)}
                  </span>
                  <button
                    type="button"
                    onClick={() => setOpenIndex(index)}
                    title="Open the record behind this evidence"
                    className="focus-ring num cursor-pointer rounded bg-[var(--surface-2)] px-1.5 py-0.5 text-[11px] text-[var(--fg-3)] transition hover:text-[var(--fg)]"
                  >
                    {item.source_ref ?? 'open record'}
                  </button>
                </div>

                <div className="flex items-center gap-2.5">
                  {verdict ? (
                    <VerdictBadge label={verdict.label} confidence={verdict.confidence} />
                  ) : (
                    <span className="text-[11.5px] text-[var(--fg-3)]">
                      {stale ? 'needs re-assessment' : 'not assessed'}
                    </span>
                  )}
                  {onChanged && (
                    <button
                      type="button"
                      onClick={() => void remove(index)}
                      disabled={removing !== null}
                      title="Remove this evidence"
                      aria-label={`Remove ${evidenceLabel(item.type)}`}
                      className="focus-ring grid size-8 place-items-center rounded text-[16px] leading-none text-[var(--fg-3)] transition hover:bg-[var(--risk-soft)] hover:text-[var(--risk)]"
                    >
                      &times;
                    </button>
                  )}
                </div>
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
            </li>
          )
        })}
      </ol>

      {onChanged && <AddEvidence disputeId={disputeId} onAdded={onChanged} />}

      {openIndex !== null && (
        <EvidenceDocumentViewer
          disputeId={disputeId}
          index={openIndex}
          verdict={byIndex.get(openIndex)}
          onClose={() => setOpenIndex(null)}
        />
      )}
    </>
  )
}

const EVIDENCE_TYPES: EvidenceType[] = [
  'delivery_proof',
  'communication_log',
  'device_signal',
  'order_history',
  'other',
]

/**
 * Attach evidence to a live case.
 *
 * A chosen file is read in the browser and its text dropped into the box, not uploaded.
 * That is deliberate for an explainability product: the merchant sees the exact text the
 * model will score before committing it, and there is no server-side extraction step that
 * could quietly change what gets scored. It also keeps binary parsing, and its
 * dependencies, out of the system entirely.
 */
function AddEvidence({ disputeId, onAdded }: { disputeId: string; onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [type, setType] = useState<EvidenceType>('delivery_proof')
  const [content, setContent] = useState('')
  const [sourceRef, setSourceRef] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      await api.addEvidence(disputeId, {
        type,
        content: content.trim(),
        source_ref: sourceRef.trim() || null,
      })
      setContent('')
      setSourceRef('')
      setOpen(false)
      onAdded()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function readFile(file: File) {
    setError(null)
    try {
      const text = await file.text()
      setContent(text.slice(0, 4000))
      if (!sourceRef.trim()) setSourceRef(file.name)
    } catch {
      setError('Could not read that file as text.')
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="focus-ring mt-2.5 w-full rounded-[var(--radius-card)] border border-dashed px-4 py-3 text-[12.5px] text-[var(--fg-3)] transition hover:text-[var(--fg)]"
        style={{ borderColor: 'var(--line)' }}
      >
        + Add evidence
      </button>
    )
  }

  return (
    <div className="surface rise mt-2.5 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={type}
          onChange={(e) => setType(e.target.value as EvidenceType)}
          aria-label="Evidence type"
          className="focus-ring rounded-[var(--radius-control)] bg-[var(--surface-2)] px-2.5 py-1.5 text-[12px] outline-none"
        >
          {EVIDENCE_TYPES.map((t) => (
            <option key={t} value={t}>
              {evidenceLabel(t)}
            </option>
          ))}
        </select>
        <input
          value={sourceRef}
          onChange={(e) => setSourceRef(e.target.value)}
          placeholder="reference (optional)"
          aria-label="Source reference"
          className="focus-ring num min-w-40 flex-1 rounded-[var(--radius-control)] bg-[var(--surface-2)] px-2.5 py-1.5 text-[12px] outline-none"
        />
        <label className="file-picker cursor-pointer rounded-[var(--radius-control)] px-2.5 py-1.5 text-[12px] text-[var(--fg-3)] transition hover:text-[var(--fg)]">
          Read a file
          <input
            type="file"
            accept=".txt,.csv,.md,.json,.log,text/*"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void readFile(f)
            }}
          />
        </label>
      </div>

      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={4}
        aria-label="Evidence text"
        placeholder="The exact text the model will score."
        aria-invalid={Boolean(error)}
        className="focus-ring mt-2.5 w-full resize-y rounded-[var(--radius-control)] bg-[var(--surface-2)] p-3 text-[13px] leading-[1.6] outline-none transition focus:bg-[var(--surface)]"
      />

      {error && (
        <p className="mt-2 text-[11.5px] text-[var(--risk)]" role="alert">
          {error}
        </p>
      )}

      <div className="mt-2.5 flex justify-end gap-2">
        <Button onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={submit} disabled={busy || !content.trim()}>
          {busy ? 'Adding…' : 'Add evidence'}
        </Button>
      </div>
    </div>
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
