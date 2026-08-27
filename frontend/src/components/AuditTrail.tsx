import { useState } from 'react'
import { parseApiDate, type AuditLogEntry } from '../api/client'
import { RECOMMENDATIONS } from '../lib/labels'
import { Surface, toneDot } from './ui'

function formatTimestamp(iso: string | null): string {
  if (!iso) return '—'
  return parseApiDate(iso).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

/**
 * The audit trail, including the "would submit to Razorpay" payload.
 *
 * CLAUDE.md Section 7 requires this shown clearly labelled: the payload was built and
 * logged but never transmitted, because the dispute is synthetic and does not exist on
 * Razorpay's side. The labelling stays blunt rather than reassuring.
 */
export function AuditTrail({ entries }: { entries: AuditLogEntry[] }) {
  if (!entries.length) {
    return (
      <Surface className="p-5 text-[12.5px] text-[var(--fg-3)]">
        No entries yet. Approving or rejecting records one, with the exact payload.
      </Surface>
    )
  }

  return (
    <ol className="space-y-2.5">
      {entries.map((entry) => (
        <AuditEntry key={entry.id} entry={entry} />
      ))}
    </ol>
  )
}

/**
 * A withdrawal carries approved_by_human = false, exactly as a rejection does, so reading
 * that flag alone labelled every retraction "Rejected by human" — a different act, and a
 * materially misleading thing to write in an audit trail. The withdrawn flag is checked
 * first for that reason.
 */
function entryKind(entry: AuditLogEntry): { label: string; tone: 'win' | 'warn' | 'mute' } {
  if (entry.withdrawn) return { label: 'Approval withdrawn', tone: 'warn' }
  if (entry.approved_by_human) return { label: 'Approved by human', tone: 'win' }
  return { label: 'Rejected by human', tone: 'mute' }
}

function AuditEntry({ entry }: { entry: AuditLogEntry }) {
  const [open, setOpen] = useState(false)
  const copy = RECOMMENDATIONS[entry.decision.recommendation]
  const kind = entryKind(entry)

  return (
    <li className="surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className="flex items-center gap-2 text-[13px]"
          style={{ fontVariationSettings: "'wght' 510" }}
        >
          <span className={`size-1.5 rounded-full ${toneDot(kind.tone)}`} />
          {kind.label}
        </span>
        <span className="num text-[11.5px] text-[var(--fg-3)]">
          {formatTimestamp(entry.approved_at ?? null)}
        </span>
      </div>

      <dl className="mt-2.5 flex flex-wrap gap-x-6 gap-y-1 text-[12px] text-[var(--fg-2)]">
        <div className="flex gap-1.5">
          <dt className="text-[var(--fg-3)]">Call</dt>
          <dd>{copy.label}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-[var(--fg-3)]">Confidence</dt>
          <dd className="num">{(entry.decision.confidence * 100).toFixed(0)}%</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-[var(--fg-3)]">Model</dt>
          <dd className="num text-[11px]">{entry.decision.model_version}</dd>
        </div>
      </dl>

      {entry.note && (
        <p className="mt-2 text-[11.5px] leading-relaxed text-[var(--fg-3)]">{entry.note}</p>
      )}

      {entry.would_be_razorpay_payload && (
        <div
          className="mt-3 rounded-[var(--radius-control)] p-3"
          style={{ background: 'var(--warn-soft)' }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p
              className="text-[12.5px] text-[var(--warn)]"
              style={{ fontVariationSettings: "'wght' 560" }}
            >
              Would submit to Razorpay — not sent
            </p>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="text-[11.5px] text-[var(--warn)] underline-offset-2 hover:underline"
            >
              {open ? 'Hide' : 'Show payload'}
            </button>
          </div>
          <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--fg-2)]">
            The dispute is synthetic, so this was built and logged rather than transmitted.
            Blocked in two places in the backend, each with a test.
          </p>
          {open && (
            <pre
              className="rise mt-2 max-h-72 overflow-auto rounded-[6px] p-3 text-[11px] leading-relaxed text-[var(--fg-2)]"
              style={{ background: 'var(--surface)' }}
            >
              {JSON.stringify(entry.would_be_razorpay_payload, null, 2)}
            </pre>
          )}
        </div>
      )}
    </li>
  )
}
