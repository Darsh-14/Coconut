import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  api,
  type ClaimVerdict,
  type EvidenceDocument,
  type EvidenceDocumentKind,
} from '../api/client'
import { Badge, Button, Skeleton } from './ui'

/**
 * The record behind an evidence item's source_ref.
 *
 * Every source_ref in the bundle used to be a dangling string. This opens the one you
 * clicked. The body is the evidence content verbatim — the backend renderer is forbidden
 * from adding to it — and the SHA-256 at the foot is of exactly the text the verification
 * engine scored, so a reviewer can confirm the document and the verdict describe the same
 * bytes rather than taking it on trust.
 */

const KIND_LABEL: Record<EvidenceDocumentKind, string> = {
  proof_of_delivery: 'Delivery record',
  support_transcript: 'Communication',
  order_record: 'Order record',
  device_report: 'Device signal',
  generic: 'Record',
}

export function EvidenceDocumentViewer({
  disputeId,
  index,
  verdict,
  onClose,
}: {
  disputeId: string
  index: number
  verdict?: ClaimVerdict
  onClose: () => void
}) {
  const [doc, setDoc] = useState<EvidenceDocument | null>(null)
  const [error, setError] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    let live = true
    setDoc(null)
    setError(null)
    api
      .evidenceDocument(disputeId, index)
      .then((d) => live && setDoc(d))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [disputeId, index])

  // Escape closes, and the page behind must not scroll while a record is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [onClose])

  const stop = useCallback((e: React.MouseEvent) => e.stopPropagation(), [])

  // Rendered through a portal, deliberately. `position: fixed` is resolved against the
  // nearest ancestor that establishes a containing block, and any ancestor carrying a
  // transform does so -- including one whose animation merely *ends* at `transform: none`,
  // because fill-mode: both retains the computed identity matrix rather than the keyword.
  // The case page wraps its tab panel in `.rise`, which did exactly that and clipped this
  // dialog to the evidence column. A portal to <body> makes the dialog independent of
  // wherever it happens to be mounted.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8"
      style={{
        // Opaque enough that dense page content behind cannot compete with the record.
        background: 'color-mix(in srgb, var(--bg) 88%, transparent)',
        backdropFilter: 'saturate(140%) blur(6px)',
        WebkitBackdropFilter: 'saturate(140%) blur(6px)',
      }}
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-doc-title"
        onClick={stop}
        className="rise flex max-h-[86vh] w-full max-w-2xl flex-col overflow-hidden rounded-[var(--radius-card)]"
        style={{ background: 'var(--surface)', boxShadow: 'var(--shadow-pop)' }}
      >
        {error ? (
          <div className="p-5">
            <p className="text-[13px] text-[var(--risk)]">{error}</p>
            <Button className="mt-3" onClick={onClose}>
              Close
            </Button>
          </div>
        ) : !doc ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-28 w-full rounded-[10px]" />
          </div>
        ) : (
          <>
            <header
              className="flex shrink-0 items-start justify-between gap-4 border-b p-5"
              style={{ borderColor: 'var(--line)' }}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2
                    id="evidence-doc-title"
                    className="truncate text-[15px]"
                    style={{ fontVariationSettings: "'wght' 590" }}
                  >
                    {doc.title}
                  </h2>
                  <Badge>{KIND_LABEL[doc.kind]}</Badge>
                </div>
                <p className="mt-1 text-[12px] text-[var(--fg-3)]">{doc.system_of_record}</p>
              </div>
              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                aria-label="Close record"
                className="focus-ring shrink-0 rounded-[var(--radius-inner)] px-2 py-1 text-[18px] leading-none text-[var(--fg-3)] transition hover:text-[var(--fg)]"
              >
                &times;
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="p-5">
              <DocumentBody doc={doc} span={verdict?.highlighted_span ?? null} />
            </div>

            <dl
              className="grid gap-x-6 gap-y-2.5 border-t p-5 sm:grid-cols-2"
              style={{ borderColor: 'var(--line)' }}
            >
              {doc.fields.map((f) => {
                const isHash = f.label.startsWith('Content hash')
                return (
                  <div key={f.label} className={isHash ? 'sm:col-span-2' : ''}>
                    <dt className="text-[10.5px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
                      {f.label}
                    </dt>
                    <dd
                      className={`mt-0.5 break-all text-[12px] text-[var(--fg-2)] ${
                        isHash || f.label === 'Reference' ? 'num' : ''
                      }`}
                    >
                      {f.value}
                    </dd>
                  </div>
                )
              })}
            </dl>
            </div>

            <footer
              className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t p-4"
              style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}
            >
              <p className="max-w-md text-[11px] leading-relaxed text-[var(--fg-3)]">
                {doc.synthetic_notice}
              </p>
              <a
                href={api.evidenceDownloadUrl(disputeId, index)}
                download
                className="focus-ring pressable shrink-0 rounded-[var(--radius-control)] px-3 py-1.5 text-[12px] text-[var(--fg-2)] transition hover:text-[var(--fg)]"
                style={{ boxShadow: 'var(--shadow-line)', background: 'var(--surface)' }}
              >
                Download
              </a>
            </footer>
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}

/** Renders the body in the shape its reference implies. Never alters the text. */
function DocumentBody({ doc, span }: { doc: EvidenceDocument; span: string | null }) {
  const lines = doc.body.split(/\r?\n/)

  if (doc.body_format === 'csv' && lines.length > 1) {
    const rows = lines.filter((l) => l.trim()).map((l) => l.split(','))
    const [head, ...body] = rows
    return (
      <div
        className="overflow-x-auto rounded-[var(--radius-control)]"
        style={{ boxShadow: 'var(--shadow-line)' }}
      >
        <table className="w-full text-left text-[12px]">
          <thead>
            <tr style={{ background: 'var(--surface-2)' }}>
              {head.map((cell, i) => (
                <th
                  key={i}
                  className="px-3 py-2 text-[11px] uppercase tracking-[0.05em] text-[var(--fg-3)]"
                >
                  {cell.trim()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, r) => (
              <tr key={r} className="hairline">
                {row.map((cell, c) => (
                  <td key={c} className="num px-3 py-2 text-[var(--fg-2)]">
                    {cell.trim()}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (doc.body_format === 'transcript' && lines.length > 1) {
    return (
      <div className="space-y-1.5">
        {lines.map((line, i) => (
          <p key={i} className="text-[13px] leading-[1.65] text-[var(--fg-2)]">
            <Marked text={line} span={span} />
          </p>
        ))}
      </div>
    )
  }

  return (
    <blockquote
      className="rounded-[var(--radius-control)] p-4 text-[13.5px] leading-[1.7] text-[var(--fg-2)]"
      style={{ background: 'var(--surface-2)' }}
    >
      <Marked text={doc.body} span={span} />
    </blockquote>
  )
}

/** The same span the case page underlines, so the two views agree. */
function Marked({ text, span }: { text: string; span: string | null }) {
  if (!span) return <>{text}</>
  const at = text.indexOf(span)
  if (at === -1) return <>{text}</>
  return (
    <>
      {text.slice(0, at)}
      <mark className="span">{span}</mark>
      {text.slice(at + span.length)}
    </>
  )
}
