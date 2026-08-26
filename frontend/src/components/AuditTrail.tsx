import { useState } from 'react'
import type { AuditLogEntry } from '../api/client'

function formatTimestamp(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

/**
 * The audit trail, including the "would submit to Razorpay" payload.
 *
 * CLAUDE.md Section 7 requires this to be shown clearly labelled: the payload was built
 * and logged but never transmitted, because the dispute is synthetic and does not exist
 * on Razorpay's side. The labelling here is deliberately blunt rather than reassuring.
 */
export function AuditTrail({ entries }: { entries: AuditLogEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No audit entries yet. Approving or rejecting a recommendation records one here.
      </p>
    )
  }

  return (
    <ol className="space-y-3">
      {entries.map((entry) => (
        <AuditEntry key={entry.id} entry={entry} />
      ))}
    </ol>
  )
}

function AuditEntry({ entry }: { entry: AuditLogEntry }) {
  const [showPayload, setShowPayload] = useState(false)

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-slate-900">
          {entry.approved_by_human ? 'Approved by human' : 'Rejected by human'}
        </span>
        <span className="text-xs text-slate-500">
          {formatTimestamp(entry.approved_at)}
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-500">Recommendation</dt>
        <dd className="font-medium">{entry.decision.recommendation.replace(/_/g, ' ')}</dd>
        <dt className="text-slate-500">Confidence</dt>
        <dd className="font-mono tabular-nums">
          {(entry.decision.confidence * 100).toFixed(1)}%
        </dd>
        <dt className="text-slate-500">Model</dt>
        <dd className="font-mono text-xs">{entry.decision.model_version}</dd>
      </dl>

      {entry.would_be_razorpay_payload && (
        <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-amber-900">
              Would submit to Razorpay — not sent
            </p>
            <button
              type="button"
              onClick={() => setShowPayload((v) => !v)}
              className="rounded border border-amber-400 px-2 py-0.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
            >
              {showPayload ? 'Hide payload' : 'Show payload'}
            </button>
          </div>
          <p className="mt-1 text-xs text-amber-800">
            This dispute is synthetic and does not exist on Razorpay's side, so the request
            below was built and logged rather than transmitted. Recourse never submits to a
            bank or network automatically.
          </p>
          {showPayload && (
            <pre className="mt-2 max-h-72 overflow-auto rounded bg-white p-3 text-xs leading-relaxed text-slate-800">
              {JSON.stringify(entry.would_be_razorpay_payload, null, 2)}
            </pre>
          )}
        </div>
      )}
    </li>
  )
}
