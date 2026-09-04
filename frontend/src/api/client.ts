/**
 * Typed client for the Coconut API.
 *
 * Types mirror backend/app/models/schemas.py (CLAUDE.md Section 6). All requests go to
 * relative /api/* paths, which the Vite dev server proxies to the backend, so no base-URL
 * configuration is needed anywhere.
 */

export type DisputePhase =
  | 'fraud'
  | 'retrieval'
  | 'chargeback'
  | 'pre_arbitration'
  | 'arbitration'

export type DisputeStatus = 'pending' | 'decided' | 'approved' | 'submitted'

export type VerdictLabel = 'support' | 'contradict' | 'neutral'

export type Recommendation =
  | 'CONTEST'
  | 'ACCEPT'
  | 'NEEDS_HUMAN_REVIEW'
  | 'NO_ACTION_NEEDED'

export type PaymentRail = 'upi' | 'rupay' | 'card'

export interface CalibrationResult {
  alpha: number
  delta: number
  calibrated_threshold: number | null
  achievable: boolean
  calibration_set_size: number
  n_above_threshold: number
  empirical_fp_rate_on_calibration: number | null
  hoeffding_slack: number | null
  guarantee_statement: string
  smallest_achievable_alpha: number | null
}

export interface GuaranteeVerification {
  alpha: number | null
  observed_fp_rate_on_test: number | null
  guarantee_held: boolean | null
  n_contested: number
  coverage: number
  n_test: number
}

export type URCSDisposition =
  | 'AUTO_REJECT'
  | 'AUTO_ACCEPT'
  | 'PROCEEDS_TO_MERCHANT'
  | 'UNKNOWN'

export interface DisputeBudget {
  payer_ref: string
  customer_disputes_30d: number
  payer_payee_disputes_30d: number
  customer_cap_remaining: number
  payer_payee_cap_remaining: number
  window_resets_at: string
}

export interface URCSForecast {
  predicted_disposition: URCSDisposition
  predicted_reason_code: string | null
  rgnb_re_raise_possible: boolean
  budget: DisputeBudget
  explanation: string
  rules_verified_on: string
}

export type EvidenceType =
  | 'delivery_proof'
  | 'communication_log'
  | 'device_signal'
  | 'order_history'
  | 'other'

export interface EvidenceItem {
  type: EvidenceType
  content: string
  source_ref: string | null
}

export interface DisputeCreate {
  reason_code: string
  claim_text: string
  amount: number
  phase?: DisputePhase
  rail?: PaymentRail
  payer_ref?: string | null
  currency?: string
}

export interface EvidenceAdd {
  type: EvidenceType
  content: string
  source_ref?: string | null
}

/** Everything the browser needs to open Razorpay Checkout. `key_id` is the publishable
 *  test key; the secret never leaves the server. */
export interface BackingOrder {
  dispute_id: string
  order_id: string
  amount: number
  currency: string
  key_id: string
  description: string
  reused: boolean
}

export interface BackingStatus {
  dispute_id: string
  payment_id: string
  payment_is_real: boolean
  order_id: string | null
  order_status: string | null
  payments_seen: number
  message: string
}

export type EvidenceDocumentKind =
  | 'proof_of_delivery'
  | 'support_transcript'
  | 'order_record'
  | 'device_report'
  | 'generic'

export interface EvidenceField {
  label: string
  value: string
}

/** An evidence item rendered as the record its source_ref implies. `body` is verbatim. */
export interface EvidenceDocument {
  dispute_id: string
  evidence_index: number
  source_ref: string | null
  kind: EvidenceDocumentKind
  title: string
  system_of_record: string
  fields: EvidenceField[]
  body: string
  body_format: 'text' | 'transcript' | 'csv'
  content_hash: string
  synthetic_notice: string
}

export interface Dispute {
  dispute_id: string
  payment_id: string
  phase: DisputePhase
  reason_code: string
  claim_text: string
  amount: number // paise
  currency: string
  raised_at: string
  respond_by: string
  evidence_bundle: EvidenceItem[]
  ground_truth_label: string | null
  rail: PaymentRail
  payer_ref: string | null
}

export interface ClaimVerdict {
  evidence_index: number
  label: VerdictLabel
  confidence: number
  highlighted_span: string | null
}

export interface Decision {
  dispute_id: string
  recommendation: Recommendation
  confidence: number
  claim_verdicts: ClaimVerdict[]
  drafted_packet: string | null
  decided_at: string
  model_version: string
  /** The active risk-budget threshold captured with this decision for replayability. */
  calibrated_threshold_used: number | null
}

export interface AuditLogEntry {
  id: number
  dispute_id: string
  decision_id: number
  decision: Decision
  approved_by_human: boolean
  approved_at: string | null
  created_at: string
  submitted_to_razorpay: boolean
  would_be_razorpay_payload: Record<string, unknown> | null
  /** True when this entry retracts an earlier approval rather than granting one. */
  withdrawn: boolean
  note: string | null
}

export interface DisputeSummary {
  dispute_id: string
  phase: DisputePhase
  reason_code: string
  amount: number
  currency: string
  respond_by: string
  status: DisputeStatus
  payment_id: string
  payment_is_real: boolean
  /** Null until /decide has run for this dispute. */
  recommendation: Recommendation | null
  confidence: number | null
  rail: PaymentRail
  urcs_reason_code: string | null
}

export interface DisputeDetail {
  dispute: Dispute
  latest_decision: Decision | null
  /** Persisted identity used as an optimistic token for decision-bound writes. */
  latest_decision_id: number | null
  decision_rationale: string | null
  audit_log: AuditLogEntry[]
  status: DisputeStatus
  payment_is_real: boolean
  /** Evidence changed after the latest decision: verdicts no longer line up with the
   *  current bundle and must not be drawn against it. */
  decision_is_stale: boolean
  /** The merchant's unapproved working copy of the packet, if they have edited it. */
  edited_packet: string | null
}

export interface EvalMetrics {
  precision: number
  recall: number
  f1: number
  confusion_matrix: {
    tp: number
    fp: number
    fn: number
    tn: number
    flagged_human: number
  }
  false_positive_cost_estimate_inr: number
  coverage: number
  n_evaluated: number
  auto_resolved: number
}

export class ApiError extends Error {
  // Declared explicitly rather than as a constructor parameter property: the project's
  // tsconfig sets erasableSyntaxOnly, which disallows that shorthand.
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    // A network-level failure means the backend is not running; say so plainly rather
    // than surfacing a bare "Failed to fetch" to the user.
    throw new ApiError(
      'Cannot reach the backend. Start it with `uvicorn app.main:app --reload` from backend/.',
      0,
    )
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      /* response had no JSON body; keep the status line */
    }
    throw new ApiError(detail, response.status)
  }

  return (await response.json()) as T
}

export const api = {
  listDisputes: () => request<DisputeSummary[]>('/disputes'),
  getDispute: (id: string) => request<DisputeDetail>(`/disputes/${id}`),
  decide: (id: string) => request<Decision>(`/disputes/${id}/decide`, { method: 'POST' }),
  approve: (id: string, decisionId: number, approved: boolean, editedPacket: string | null) =>
    request<AuditLogEntry>(`/disputes/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ decision_id: decisionId, approved, edited_packet: editedPacket }),
    }),
  evaluate: () => request<EvalMetrics>('/evaluate', { method: 'POST' }),
  urcsForecast: (id: string) => request<URCSForecast>(`/disputes/${id}/urcs-forecast`),
  calibrate: (alpha: number, delta = 0.1) =>
    request<CalibrationResult>('/calibrate', {
      method: 'POST',
      body: JSON.stringify({ alpha, delta }),
    }),
  verifyGuarantee: () => request<GuaranteeVerification>('/verify-guarantee'),
  savePacketDraft: (id: string, decisionId: number, text: string) =>
    request<{ decision_id: number; text: string }>(`/disputes/${id}/packet-draft`, {
      method: 'PUT',
      body: JSON.stringify({ decision_id: decisionId, text }),
    }),
  withdraw: (id: string, approvalId: number) =>
    request<AuditLogEntry>(`/disputes/${id}/withdraw?approval_id=${approvalId}`, {
      method: 'POST',
    }),
  packetUrl: (id: string, decisionId: number) =>
    `/api/disputes/${id}/packet.txt?decision_id=${decisionId}`,
  wouldSubmitUrl: (id: string) => `/api/disputes/${id}/would-submit.json`,
  createDispute: (body: DisputeCreate) =>
    request<Dispute>('/disputes', { method: 'POST', body: JSON.stringify(body) }),
  addEvidence: (id: string, body: EvidenceAdd) =>
    request<Dispute>(`/disputes/${id}/evidence`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  removeEvidence: (id: string, index: number) =>
    request<Dispute>(`/disputes/${id}/evidence/${index}`, { method: 'DELETE' }),
  createBackingOrder: (id: string) =>
    request<BackingOrder>(`/disputes/${id}/backing-order`, { method: 'POST' }),
  backingStatus: (id: string) => request<BackingStatus>(`/disputes/${id}/backing-status`),
  evidenceDocument: (id: string, index: number) =>
    request<EvidenceDocument>(`/disputes/${id}/evidence/${index}/document`),
  evidenceDownloadUrl: (id: string, index: number) =>
    `/api/disputes/${id}/evidence/${index}/download`,
}

// --- formatting helpers -------------------------------------------------------------

/** Paise to a formatted rupee string. Amounts are stored in paise throughout. */
export function formatInr(paise: number): string {
  return `₹${(paise / 100).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/**
 * Paise to a compact rupee string for headline figures: ₹4.2L, ₹32.5k, ₹499.
 * Indian grouping, because a merchant reading a portfolio total thinks in lakhs.
 */
export function formatInrCompact(paise: number): string {
  const rupees = paise / 100
  if (rupees >= 1e7) return `₹${(rupees / 1e7).toFixed(2)}Cr`
  if (rupees >= 1e5) return `₹${(rupees / 1e5).toFixed(1)}L`
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(1)}k`
  return `₹${Math.round(rupees)}`
}

/**
 * The backend serialises naive UTC datetimes, so the string carries no offset and
 * `new Date(s)` would read it as local time — shifting every countdown by the viewer's
 * UTC offset (5h30m in IST). Treat an offset-less timestamp as UTC, which is what it is.
 */
export function parseApiDate(iso: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso)
  return new Date(hasZone ? iso : `${iso}Z`)
}

export interface Countdown {
  label: string
  /** Section 12: highlight red under 48 hours. */
  urgent: boolean
  expired: boolean
}

export function countdownTo(iso: string, now: Date = new Date()): Countdown {
  const target = parseApiDate(iso).getTime()
  const ms = target - now.getTime()

  if (ms <= 0) return { label: 'overdue', urgent: true, expired: true }

  const hours = ms / 36e5
  const days = Math.floor(hours / 24)
  const remainingHours = Math.floor(hours % 24)

  const label = days > 0 ? `${days}d ${remainingHours}h` : `${Math.floor(hours)}h`
  return { label, urgent: hours < 48, expired: false }
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}
