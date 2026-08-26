/**
 * Typed client for the Recourse API.
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

export type Recommendation = 'CONTEST' | 'ACCEPT' | 'NEEDS_HUMAN_REVIEW'

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
}

export interface AuditLogEntry {
  id: number
  dispute_id: string
  decision: Decision
  approved_by_human: boolean
  approved_at: string | null
  submitted_to_razorpay: boolean
  would_be_razorpay_payload: Record<string, unknown> | null
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
}

export interface DisputeDetail {
  dispute: Dispute
  latest_decision: Decision | null
  decision_rationale: string | null
  audit_log: AuditLogEntry[]
  status: DisputeStatus
  payment_is_real: boolean
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
  approve: (id: string, approved: boolean, editedPacket: string | null) =>
    request<AuditLogEntry>(`/disputes/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved, edited_packet: editedPacket }),
    }),
  evaluate: () => request<EvalMetrics>('/evaluate', { method: 'POST' }),
}

// --- formatting helpers -------------------------------------------------------------

/** Paise to a formatted rupee string. Amounts are stored in paise throughout. */
export function formatInr(paise: number): string {
  return `₹${(paise / 100).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export interface Countdown {
  label: string
  /** Section 12: highlight red under 48 hours. */
  urgent: boolean
  expired: boolean
}

export function countdownTo(iso: string, now: Date = new Date()): Countdown {
  const target = new Date(iso).getTime()
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
