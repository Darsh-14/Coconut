import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, countdownTo, formatInr, parseApiDate, type DisputeDetail } from '../api/client'
import { AuditTrail } from '../components/AuditTrail'
import { EvidenceClaimMap, EvidenceSummary } from '../components/EvidenceClaimMap'
import { PhaseBadge, RecommendationBanner, StatusBadge } from '../components/ConfidenceBadge'
import { phaseCopy, reasonCopy, RECOMMENDATIONS } from '../lib/labels'
import { Button, Progress, Skeleton, Surface } from '../components/ui'

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
      setNotice(approved ? 'Payload built and logged — not transmitted.' : 'Recorded as rejected.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (error) {
    return (
      <div className="space-y-4">
        <BackLink />
        <Surface className="p-5 text-[13px] text-[var(--risk)]">{error}</Surface>
      </div>
    )
  }

  if (!detail) return <CaseSkeleton />

  const { dispute, latest_decision: decision } = detail
  const countdown = countdownTo(dispute.respond_by)
  const reason = reasonCopy(dispute.reason_code)
  const isContest = decision?.recommendation === 'CONTEST'
  const actioned = detail.status === 'approved' || detail.status === 'submitted'

  return (
    <div className="space-y-6">
      <BackLink />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1
              className="text-[22px] tracking-[-0.022em]"
              style={{ fontVariationSettings: "'wght' 590" }}
            >
              {reason.short}
            </h1>
            <PhaseBadge phase={dispute.phase} />
            <StatusBadge status={detail.status} />
          </div>
          <p className="num mt-1 text-[12px] text-[var(--fg-3)]">{dispute.dispute_id}</p>
        </div>

        <div className="text-right">
          <p
            className="num text-[21px] tracking-[-0.022em]"
            style={{ fontVariationSettings: "'wght' 560" }}
          >
            {formatInr(dispute.amount)}
          </p>
          <p
            className={`num text-[12px] ${countdown.urgent ? 'text-[var(--risk)]' : 'text-[var(--fg-3)]'}`}
          >
            {countdown.label} to respond
          </p>
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="space-y-5">
          <Surface className="p-5" >
            <p className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
              Bank&rsquo;s claim
            </p>
            <blockquote className="mt-2 text-[15px] leading-[1.6]">
              {dispute.claim_text}
            </blockquote>
          </Surface>

          {notice && (
            <p className="rise surface p-3.5 text-[12.5px] text-[var(--fg-2)]">{notice}</p>
          )}

          {decision ? (
            <RecommendationBanner
              recommendation={decision.recommendation}
              confidence={decision.confidence}
              rationale={detail.decision_rationale}
            />
          ) : (
            <NotAssessed busy={busy === 'deciding'} onRun={runDecide} />
          )}

          <section>
            <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-baseline gap-2.5">
                <h2 className="text-[13px]" style={{ fontVariationSettings: "'wght' 590" }}>
                  Evidence
                </h2>
                <EvidenceSummary verdicts={decision?.claim_verdicts ?? []} />
              </div>
              {decision && (
                <Button size="sm" onClick={runDecide} disabled={busy !== null}>
                  {busy === 'deciding' ? 'Re-assessing…' : 'Re-assess'}
                </Button>
              )}
            </div>
            <EvidenceClaimMap
              evidence={dispute.evidence_bundle}
              verdicts={decision?.claim_verdicts ?? []}
            />
            {decision && <HowItWorks />}
          </section>

          {isContest && (
            <section className="surface p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-[13px]" style={{ fontVariationSettings: "'wght' 590" }}>
                  Representment draft
                </h2>
                {decision.drafted_packet && packet !== decision.drafted_packet && (
                  <button
                    type="button"
                    onClick={() => setPacket(decision.drafted_packet ?? '')}
                    className="text-[11.5px] text-[var(--fg-3)] hover:text-[var(--fg)]"
                  >
                    Revert to draft
                  </button>
                )}
              </div>
              <textarea
                value={packet}
                onChange={(e) => setPacket(e.target.value)}
                rows={16}
                spellCheck={false}
                className="mt-3 w-full rounded-[var(--radius-control)] bg-[var(--surface-2)] p-4 font-mono text-[12px] leading-[1.7] text-[var(--fg-2)] outline-none transition focus:bg-[var(--surface)] focus:shadow-[var(--shadow-line)]"
              />
            </section>
          )}

          <section>
            <h2
              className="mb-2.5 text-[13px]"
              style={{ fontVariationSettings: "'wght' 590" }}
            >
              Audit trail
            </h2>
            <AuditTrail entries={detail.audit_log} />
          </section>
        </div>

        <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start">
          <Surface className="p-4">
            <dl className="space-y-3 text-[12px]">
              <Fact label="Due">
                {parseApiDate(dispute.respond_by).toLocaleString('en-IN', {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                })}
              </Fact>
              <Fact label="Stage">{phaseCopy(dispute.phase).meaning}</Fact>
              <Fact label="Payment">
                <span className="num">{dispute.payment_id}</span>
                {detail.payment_is_real && (
                  <span className="ml-1.5 text-[var(--win)]">real</span>
                )}
              </Fact>
              <Fact label="Wins on">{reason.wins}</Fact>
            </dl>
          </Surface>

          {decision && (
            <Surface className="p-4">
              <Button
                variant="primary"
                className="w-full"
                onClick={() => runApprove(true)}
                disabled={busy !== null}
              >
                {busy === 'approving'
                  ? 'Recording…'
                  : RECOMMENDATIONS[decision.recommendation].action}
              </Button>
              <Button
                className="mt-2 w-full"
                onClick={() => runApprove(false)}
                disabled={busy !== null}
              >
                Reject
              </Button>
              {actioned && (
                <p className="mt-2.5 text-[11px] text-[var(--fg-3)]">
                  Already actioned — approving appends a new entry.
                </p>
              )}
            </Surface>
          )}
        </aside>
      </div>
    </div>
  )
}

// --- pieces ---------------------------------------------------------------------------

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">{label}</dt>
      <dd className="mt-0.5 leading-snug text-[var(--fg-2)]">{children}</dd>
    </div>
  )
}

function NotAssessed({ busy, onRun }: { busy: boolean; onRun: () => void }) {
  return (
    <Surface className="p-5">
      {busy ? (
        <>
          <p className="text-[13px]" style={{ fontVariationSettings: "'wght' 510" }}>
            Reading evidence…
          </p>
          <p className="mt-1 text-[12px] text-[var(--fg-3)]">
            First run after startup loads the model — about 15 seconds.
          </p>
          <div className="mt-3">
            <Progress />
          </div>
        </>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] text-[var(--fg-2)]">Not assessed yet.</p>
          <Button variant="primary" onClick={onRun}>
            Run assessment
          </Button>
        </div>
      )}
    </Surface>
  )
}

/**
 * The two-signal design is the actual engineering result here and was invisible in the
 * UI. Collapsed and terse: available to audit, not in the way.
 */
function HowItWorks() {
  return (
    <details className="group mt-3">
      <summary className="cursor-pointer list-none text-[12px] text-[var(--fg-3)] transition hover:text-[var(--fg)]">
        How each verdict is reached
        <span className="ml-1.5 inline-block transition group-open:rotate-90">&rsaquo;</span>
      </summary>
      <dl className="rise mt-2.5 grid gap-2 sm:grid-cols-2">
        <div className="surface p-3.5">
          <dt className="text-[12px]" style={{ fontVariationSettings: "'wght' 510" }}>
            1 · Engagement
          </dt>
          <dd className="mt-1 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
            Does the evidence contradict the bank&rsquo;s claim at all? A gate — most
            on-topic evidence passes.
          </dd>
        </div>
        <div className="surface p-3.5">
          <dt className="text-[12px]" style={{ fontVariationSettings: "'wght' 510" }}>
            2 · Substantiation
          </dt>
          <dd className="mt-1 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
            Is it specific enough to prove the merchant&rsquo;s position? This picks the
            underlined sentence.
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-[11.5px] text-[var(--fg-3)]">
        Engagement alone scored below a coin flip — strong and weak proof both contradict
        &ldquo;it never arrived&rdquo;.
      </p>
    </details>
  )
}

function CaseSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-4 w-24" />
      <div className="flex justify-between">
        <div className="space-y-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-3 w-32" />
        </div>
        <Skeleton className="h-7 w-28" />
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="space-y-5">
          <Skeleton className="h-24 w-full rounded-[10px]" />
          <Skeleton className="h-28 w-full rounded-[10px]" />
          <Skeleton className="h-32 w-full rounded-[10px]" />
        </div>
        <Skeleton className="h-48 w-full rounded-[10px]" />
      </div>
    </div>
  )
}

function BackLink() {
  return (
    <Link
      to="/"
      className="inline-flex items-center gap-1.5 text-[12.5px] text-[var(--fg-3)] transition hover:text-[var(--fg)]"
    >
      <span aria-hidden="true">&larr;</span> Disputes
    </Link>
  )
}
