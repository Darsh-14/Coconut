import { useCallback, useEffect, useState } from 'react'
import { paths } from '../lib/routes'
import { Link, useParams } from 'react-router-dom'
import { api, countdownTo, formatInr, parseApiDate, type DisputeDetail } from '../api/client'
import { AuditTrail } from '../components/AuditTrail'
import { BackingPayment } from '../components/BackingPayment'
import { EvidenceClaimMap, EvidenceSummary } from '../components/EvidenceClaimMap'
import { PhaseBadge, RecommendationBanner, StatusBadge } from '../components/ConfidenceBadge'
import { UrcsBudgetStrip } from '../components/UrcsBudgetStrip'
import { phaseCopy, railCopy, reasonCopy, RECOMMENDATIONS } from '../lib/labels'
import { Badge, Button, Progress, Segmented, Skeleton, Surface } from '../components/ui'

type Tab = 'evidence' | 'packet' | 'audit'

export default function CaseDetail() {
  const { disputeId = '' } = useParams()
  const [detail, setDetail] = useState<DisputeDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'deciding' | 'approving' | null>(null)
  const [packet, setPacket] = useState('')
  const [savedPacket, setSavedPacket] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('evidence')
  const [draftState, setDraftState] = useState<'idle' | 'saving' | 'saved'>('idle')

  const load = useCallback(async () => {
    try {
      const next = await api.getDispute(disputeId)
      setDetail(next)
      // Prefer the merchant's saved working copy over the model's original draft.
      const nextPacket = next.edited_packet ?? next.latest_decision?.drafted_packet ?? ''
      setPacket(nextPacket)
      setSavedPacket(nextPacket)
      setDraftState('idle')
      setDraftError(null)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [disputeId])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- load updates state only after I/O
    void load()
  }, [load])

  /**
   * Autosave the representment edit.
   *
   * Debounced rather than saved per keystroke: a merchant rewriting a packet types for
   * minutes, and one PUT per character would be pointless load. 800ms is long enough to
   * batch a sentence and short enough that closing the tab rarely loses anything.
   *
   * Saving a draft is explicitly not approving it — nothing here touches the audit log.
   */
  const decisionId = detail?.latest_decision_id ?? null
  const decisionIsStale = detail?.decision_is_stale ?? true
  const decisionIsActioned = detail?.status === 'approved' || detail?.status === 'submitted'
  const modelDraft = detail?.latest_decision?.drafted_packet ?? ''
  useEffect(() => {
    if (!decisionId || decisionIsStale || decisionIsActioned || busy !== null) return
    if (packet === savedPacket) return

    let cancelled = false
    const timer = setTimeout(() => {
      setDraftState('saving')
      // Sending an empty value clears edited_packet. Persisting the model text as a human
      // edit would make "Revert to draft" reappear after the next reload.
      const draftText = packet === modelDraft ? '' : packet
      api
        .savePacketDraft(disputeId, decisionId, draftText)
        .then(() => {
          if (cancelled) return
          setSavedPacket(packet)
          setDraftState('saved')
          setDraftError(null)
        })
        .catch((e: Error) => {
          if (cancelled) return
          setDraftState('idle')
          setDraftError(`Draft not saved: ${e.message}`)
        })
    }, 800)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [
    packet,
    savedPacket,
    disputeId,
    decisionId,
    decisionIsStale,
    decisionIsActioned,
    busy,
    modelDraft,
  ])

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

  async function runWithdraw() {
    if (!detail) return
    const approvalId = standingApprovalId(detail.audit_log)
    if (!approvalId) {
      setNotice('No standing approval remains. Reloading the case.')
      await load()
      return
    }
    setBusy('approving')
    setNotice(null)
    try {
      await api.withdraw(disputeId, approvalId)
      await load()
      setTab('audit')
      setNotice('Approval withdrawn. The case is back in the queue.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function runApprove(approved: boolean) {
    if (!detail?.latest_decision_id) return
    const recommendation = detail.latest_decision?.recommendation
    if (approved && recommendation === 'CONTEST' && !packet.trim()) {
      setTab('packet')
      setDraftError('A contest cannot be approved with an empty representment packet.')
      return
    }
    setBusy('approving')
    setNotice(null)
    try {
      await api.approve(
        disputeId,
        detail.latest_decision_id,
        approved,
        approved && recommendation === 'CONTEST' ? packet : null,
      )
      await load()
      setTab('audit')
      setNotice(
        approved
          ? recommendation === 'CONTEST'
            ? 'Payload built and logged — not transmitted.'
            : 'Recommendation approval recorded; no representment was needed.'
          : 'Recorded as rejected.',
      )
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
        <Surface className="p-5">
          <p className="text-[13px] text-[var(--risk)]">{error}</p>
          <Button
            className="mt-3"
            onClick={() => {
              setError(null)
              void load()
            }}
          >
            Try again
          </Button>
        </Surface>
      </div>
    )
  }

  if (!detail) return <CaseSkeleton />

  const { dispute, latest_decision: decision } = detail
  const countdown = countdownTo(dispute.respond_by)
  const reason = reasonCopy(dispute.reason_code)
  const isContest = decision?.recommendation === 'CONTEST'
  const actioned = decisionIsActioned
  const currentDecisionEvents = detail.audit_log.filter(
    (entry) => entry.decision_id === detail.latest_decision_id,
  )
  const latestDecisionEvent = currentDecisionEvents.at(-1)
  const rejectedCurrent = Boolean(
    latestDecisionEvent &&
      !latestDecisionEvent.approved_by_human &&
      !latestDecisionEvent.withdrawn,
  )

  const tabs: Array<{ key: Tab; label: string; count?: number }> = [
    { key: 'evidence', label: 'Evidence', count: dispute.evidence_bundle.length },
    ...(isContest ? [{ key: 'packet' as const, label: 'Representment' }] : []),
    { key: 'audit', label: 'Audit', count: detail.audit_log.length || undefined },
  ]

  return (
    <div>
      <BackLink />

      <header className="mb-5 mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1
              className="text-[26px] leading-none tracking-[-0.028em]"
              style={{ fontVariationSettings: "'wght' 600" }}
            >
              {reason.short}
            </h1>
            <PhaseBadge phase={dispute.phase} />
            <Badge title={railCopy(dispute.rail).meaning}>{railCopy(dispute.rail).label}</Badge>
            <StatusBadge status={detail.status} />
          </div>
          <p className="num mt-2 text-[12px] text-[var(--fg-3)]">{dispute.dispute_id}</p>
        </div>

        <div className="text-right">
          <p
            className="num text-[24px] leading-none tracking-[-0.028em]"
            style={{ fontVariationSettings: "'wght' 570" }}
          >
            {formatInr(dispute.amount)}
          </p>
          <p
            className={`num mt-1.5 text-[12px] ${countdown.urgent ? 'text-[var(--risk)]' : 'text-[var(--fg-3)]'}`}
          >
            {countdown.label} to respond
          </p>
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="space-y-4">
          <Surface className="p-5">
            <p className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
              Bank&rsquo;s claim
            </p>
            <blockquote className="mt-2 text-[15px] leading-[1.6]">
              {dispute.claim_text}
            </blockquote>
          </Surface>

          {dispute.rail === 'upi' && <UrcsBudgetStrip disputeId={dispute.dispute_id} />}

          {decision ? (
            <RecommendationBanner
              recommendation={decision.recommendation}
              confidence={decision.confidence}
              rationale={detail.decision_rationale}
            />
          ) : (
            <NotAssessed busy={busy === 'deciding'} onRun={runDecide} />
          )}

          {notice && (
            <p className="rise surface p-3.5 text-[12.5px] text-[var(--fg-2)]">{notice}</p>
          )}

          {/* Tabs, so evidence, draft and audit are not one endless scroll. */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <Segmented options={tabs} value={tab} onChange={setTab} />
            {tab === 'evidence' && (
              <div className="flex items-center gap-3">
                {!detail.decision_is_stale && (
                  <EvidenceSummary verdicts={decision?.claim_verdicts ?? []} />
                )}
                {decision && (
                  <Button
                    size="sm"
                    onClick={runDecide}
                    disabled={busy !== null || actioned}
                    title={actioned ? 'Withdraw the standing approval before re-assessing' : undefined}
                  >
                    {busy === 'deciding' ? 'Re-assessing…' : 'Re-assess'}
                  </Button>
                )}
              </div>
            )}
          </div>

          <div key={tab} className="rise">
            {tab === 'evidence' && (
              <>
                {detail.decision_is_stale && (
                  <StaleNotice
                    busy={busy !== null}
                    actioned={actioned}
                    onRun={actioned ? runWithdraw : runDecide}
                  />
                )}
                <EvidenceClaimMap
                  disputeId={dispute.dispute_id}
                  evidence={dispute.evidence_bundle}
                  verdicts={decision?.claim_verdicts ?? []}
                  stale={detail.decision_is_stale}
                  onChanged={actioned ? undefined : () => void load()}
                />
                {decision && <HowItWorks />}
              </>
            )}

            {tab === 'packet' && isContest && (
              <Surface className="p-5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-[12px] text-[var(--fg-3)]">
                    Written from the verdicts. Your edits are what get logged.
                  </p>
                  <span className="flex items-center gap-3">
                    {(draftState !== 'idle' || packet !== savedPacket) && (
                      <span className="text-[11px] text-[var(--fg-3)]">
                        {draftState === 'saving'
                          ? 'Saving…'
                          : packet !== savedPacket
                            ? 'Unsaved changes'
                            : 'Saved'}
                      </span>
                    )}
                    {decision.drafted_packet && packet !== decision.drafted_packet && (
                      <button
                        type="button"
                        onClick={() => setPacket(decision.drafted_packet ?? '')}
                        disabled={detail.decision_is_stale || actioned}
                        className="text-[11.5px] text-[var(--fg-3)] hover:text-[var(--fg)]"
                      >
                        Revert to draft
                      </button>
                    )}
                  </span>
                </div>
                <textarea
                  value={packet}
                  onChange={(e) => setPacket(e.target.value)}
                  disabled={detail.decision_is_stale || actioned}
                  rows={20}
                  spellCheck={false}
                  className="mt-3 w-full rounded-[var(--radius-control)] bg-[var(--surface-2)] p-4 font-mono text-[12px] leading-[1.7] text-[var(--fg-2)] outline-none transition focus:bg-[var(--surface)] focus:shadow-[var(--shadow-line)]"
                />
                {draftError && (
                  <p className="mt-2 text-[11.5px] text-[var(--risk)]">{draftError}</p>
                )}
                {(detail.decision_is_stale || actioned) && (
                  <p className="mt-2 text-[11.5px] text-[var(--fg-3)]">
                    {detail.decision_is_stale
                      ? 'Re-assess this evidence before editing or exporting its packet.'
                      : 'Withdraw the standing approval before editing this packet.'}
                  </p>
                )}
              </Surface>
            )}

            {tab === 'audit' && <AuditTrail entries={detail.audit_log} />}
          </div>
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
                {detail.payment_is_real ? (
                  <span className="ml-1.5 text-[var(--win)]">real</span>
                ) : (
                  <span className="ml-1.5 text-[var(--fg-3)]">placeholder</span>
                )}
              </Fact>
              <Fact label="Wins on">{reason.wins}</Fact>
            </dl>
          </Surface>

          {!detail.payment_is_real && (
            <Surface className="p-4">
              <p className="mb-2.5 text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
                Backing payment
              </p>
              <BackingPayment
                disputeId={dispute.dispute_id}
                amount={dispute.amount}
                onAttached={() => void load()}
              />
            </Surface>
          )}

          {decision && (
            <Surface className="p-4">
              {actioned ? (
                <>
                  <p
                    className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]"
                  >
                    Human action recorded
                  </p>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-[var(--fg-2)]">
                    {detail.status === 'submitted'
                      ? 'Representment prepared and logged — not transmitted.'
                      : 'Recommendation approved and recorded.'}
                  </p>
                  <Button className="mt-3 w-full" onClick={runWithdraw} disabled={busy !== null}>
                    {busy === 'approving' ? 'Working…' : 'Withdraw approval'}
                  </Button>
                  <p className="mt-2.5 text-[11px] leading-relaxed text-[var(--fg-3)]">
                    Withdrawing returns this to the queue. Nothing was ever transmitted, so
                    there is nothing to retract on Razorpay's side.
                  </p>
                </>
              ) : (
                <>
                  <Button
                    variant="primary"
                    className="w-full py-2.5"
                    onClick={() => runApprove(true)}
                    disabled={busy !== null || detail.decision_is_stale}
                  >
                    {busy === 'approving'
                      ? 'Recording…'
                      : RECOMMENDATIONS[decision.recommendation].action}
                  </Button>
                  <Button
                    className="mt-2 w-full"
                    onClick={() => runApprove(false)}
                    disabled={busy !== null || detail.decision_is_stale || rejectedCurrent}
                  >
                    {rejectedCurrent ? 'Rejected' : 'Reject'}
                  </Button>
                  {detail.decision_is_stale && (
                    <p className="mt-2.5 text-[11px] leading-relaxed text-[var(--fg-3)]">
                      Evidence changed after this assessment. Re-assess before recording a
                      human action.
                    </p>
                  )}
                </>
              )}

              {/* A packet you cannot get out of the browser is one you cannot send on. */}
              <div
                className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 border-t pt-3"
                style={{ borderColor: 'var(--line)' }}
              >
                {isContest && !detail.decision_is_stale && detail.latest_decision_id && (
                  <a
                    href={api.packetUrl(dispute.dispute_id, detail.latest_decision_id)}
                    download
                    className="focus-ring rounded text-[11.5px] text-[var(--fg-3)] transition hover:text-[var(--fg)]"
                  >
                    Download packet
                  </a>
                )}
                {isContest && detail.decision_is_stale && (
                  <span className="text-[11.5px] text-[var(--fg-3)]">
                    Packet export locked until re-assessment
                  </span>
                )}
                {detail.audit_log.some((e) => e.would_be_razorpay_payload) && (
                  <a
                    href={api.wouldSubmitUrl(dispute.dispute_id)}
                    download
                    className="focus-ring rounded text-[11.5px] text-[var(--fg-3)] transition hover:text-[var(--fg)]"
                  >
                    Download &ldquo;would submit&rdquo; payload
                  </a>
                )}
              </div>
            </Surface>
          )}
        </aside>
      </div>
    </div>
  )
}

// --- pieces ---------------------------------------------------------------------------

function standingApprovalId(entries: DisputeDetail['audit_log']): number | null {
  let standing: number | null = null
  for (const entry of entries) {
    if (entry.withdrawn) standing = null
    else if (entry.approved_by_human) standing = entry.id
  }
  return standing
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">{label}</dt>
      <dd className="mt-0.5 leading-snug text-[var(--fg-2)]">{children}</dd>
    </div>
  )
}

/** Shown when the bundle moved after the standing decision was computed. */
function StaleNotice({
  busy,
  actioned,
  onRun,
}: {
  busy: boolean
  actioned: boolean
  onRun: () => void
}) {
  return (
    <div
      className="surface mb-2.5 flex flex-wrap items-center justify-between gap-3 p-3.5"
      style={{ boxShadow: 'var(--shadow-line), inset 2px 0 0 0 var(--warn)' }}
    >
      <p className="text-[12.5px] text-[var(--fg-2)]">
        Evidence changed after this assessment. Per-item verdicts and decision-bound actions
        are locked until {actioned ? 'the standing approval is withdrawn' : 'it runs again'}.
      </p>
      <Button onClick={onRun} disabled={busy}>
        {busy ? 'Working…' : actioned ? 'Withdraw approval' : 'Re-assess'}
      </Button>
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
            First run after startup loads the model — about fifteen seconds.
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

/** The two-signal design, available to audit without sitting in the way. */
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
            1 &middot; Engagement
          </dt>
          <dd className="mt-1 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
            Does the evidence contradict the bank&rsquo;s claim at all? A gate — most
            on-topic evidence passes.
          </dd>
        </div>
        <div className="surface p-3.5">
          <dt className="text-[12px]" style={{ fontVariationSettings: "'wght' 510" }}>
            2 &middot; Substantiation
          </dt>
          <dd className="mt-1 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
            Is it specific enough to prove the merchant&rsquo;s position? This picks the
            highlighted sentence.
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
    <div className="space-y-5">
      <Skeleton className="h-4 w-24" />
      <div className="flex justify-between">
        <div className="space-y-2">
          <Skeleton className="h-7 w-52" />
          <Skeleton className="h-3 w-32" />
        </div>
        <Skeleton className="h-8 w-28" />
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="space-y-4">
          <Skeleton className="h-24 w-full rounded-[14px]" />
          <Skeleton className="h-28 w-full rounded-[14px]" />
          <Skeleton className="h-40 w-full rounded-[14px]" />
        </div>
        <Skeleton className="h-52 w-full rounded-[14px]" />
      </div>
    </div>
  )
}

function BackLink() {
  return (
    <Link
      to={paths.disputes}
      className="inline-flex items-center gap-1.5 text-[12.5px] text-[var(--fg-3)] transition hover:text-[var(--fg)]"
    >
      <span aria-hidden="true">&larr;</span> Disputes
    </Link>
  )
}
