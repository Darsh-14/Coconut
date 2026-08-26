import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, countdownTo, formatInr, type DisputeDetail } from '../api/client'
import { AuditTrail } from '../components/AuditTrail'
import { EvidenceClaimMap } from '../components/EvidenceClaimMap'
import {
  PhaseBadge,
  RecommendationBanner,
  StatusBadge,
} from '../components/ConfidenceBadge'

export default function CaseDetail() {
  const { disputeId = '' } = useParams()
  const [detail, setDetail] = useState<DisputeDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'deciding' | 'approving' | null>(null)
  const [packet, setPacket] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const next = await api.getDispute(disputeId)
      setDetail(next)
      setPacket(next.latest_decision?.drafted_packet ?? '')
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [disputeId])

  useEffect(() => {
    void load()
  }, [load])

  async function runDecide() {
    setBusy('deciding')
    setNotice(null)
    try {
      await api.decide(disputeId)
      await load()
      setNotice('Assessment complete.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function runApprove(approved: boolean) {
    setBusy('approving')
    setNotice(null)
    try {
      await api.approve(disputeId, approved, packet || null)
      await load()
      setNotice(
        approved
          ? 'Approved. The representment payload was built and logged — not transmitted.'
          : 'Rejected. Nothing was prepared for submission.',
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (error) {
    return (
      <div>
        <BackLink />
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          {error}
        </div>
      </div>
    )
  }

  if (!detail) return <p className="text-sm text-slate-500">Loading case…</p>

  const { dispute, latest_decision: decision } = detail
  const countdown = countdownTo(dispute.respond_by)
  const isContest = decision?.recommendation === 'CONTEST'
  const alreadyApproved = detail.status === 'approved' || detail.status === 'submitted'

  return (
    <div className="space-y-6">
      <BackLink />

      <header>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="font-mono text-xl font-semibold tracking-tight">
            {dispute.dispute_id}
          </h1>
          <PhaseBadge phase={dispute.phase} />
          <StatusBadge status={detail.status} />
        </div>
        <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600">
          <span>{dispute.reason_code.replace(/_/g, ' ')}</span>
          <span className="font-mono">{formatInr(dispute.amount)}</span>
          <span className={countdown.urgent ? 'font-medium text-red-700' : ''}>
            respond in {countdown.label}
          </span>
          <span
            className="font-mono text-xs"
            title={detail.payment_is_real ? 'Real test-mode payment' : 'Placeholder id'}
          >
            {dispute.payment_id}
            {detail.payment_is_real ? ' ✓ real' : ''}
          </span>
        </p>
      </header>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500">
          The bank's claim
        </h2>
        <p className="mt-1.5 text-slate-900">{dispute.claim_text}</p>
      </section>

      {notice && (
        <p className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
          {notice}
        </p>
      )}

      {decision ? (
        <RecommendationBanner
          recommendation={decision.recommendation}
          confidence={decision.confidence}
          rationale={detail.decision_rationale}
        />
      ) : (
        <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
          <p className="text-sm text-slate-600">
            This dispute has not been assessed yet.
          </p>
          <button
            type="button"
            onClick={runDecide}
            disabled={busy !== null}
            className="mt-2 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {busy === 'deciding' ? 'Assessing…' : 'Run assessment'}
          </button>
        </section>
      )}

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">
            Evidence checked against the claim
          </h2>
          {decision && (
            <button
              type="button"
              onClick={runDecide}
              disabled={busy !== null}
              className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {busy === 'deciding' ? 'Re-assessing…' : 'Re-run assessment'}
            </button>
          )}
        </div>
        <EvidenceClaimMap
          evidence={dispute.evidence_bundle}
          verdicts={decision?.claim_verdicts ?? []}
        />
      </section>

      {isContest && (
        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-900">Drafted representment</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Edit before approving. Nothing is sent to Razorpay or any bank — the payload is
            logged for review.
          </p>
          <textarea
            value={packet}
            onChange={(e) => setPacket(e.target.value)}
            rows={16}
            spellCheck={false}
            className="mt-2 w-full rounded-md border border-slate-300 p-3 font-mono text-xs leading-relaxed focus:border-slate-500 focus:outline-none"
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => runApprove(true)}
              disabled={busy !== null}
              className="rounded-md bg-green-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-800 disabled:opacity-50"
            >
              {busy === 'approving' ? 'Recording…' : 'Approve & Submit'}
            </button>
            <button
              type="button"
              onClick={() => runApprove(false)}
              disabled={busy !== null}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Reject
            </button>
            {alreadyApproved && (
              <span className="self-center text-xs text-slate-500">
                Already actioned — approving again appends another audit entry.
              </span>
            )}
          </div>
        </section>
      )}

      {decision && !isContest && (
        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-900">Human decision</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            No representment is drafted for a non-CONTEST outcome. Recording your decision
            keeps the audit trail complete.
          </p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => runApprove(true)}
              disabled={busy !== null}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Approve recommendation
            </button>
            <button
              type="button"
              onClick={() => runApprove(false)}
              disabled={busy !== null}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-900">Audit trail</h2>
        <AuditTrail entries={detail.audit_log} />
      </section>
    </div>
  )
}

function BackLink() {
  return (
    <Link to="/" className="text-sm text-slate-600 hover:text-slate-900">
      ← Back to queue
    </Link>
  )
}
