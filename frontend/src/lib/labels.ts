/**
 * Plain-English translation layer.
 *
 * The API speaks in reason codes, phases and NLI labels. Nothing raw reaches the screen.
 * Copy here is deliberately terse — a label, not an explanation. Anything that needs a
 * paragraph belongs in a tooltip or nowhere.
 */

import type { Recommendation, VerdictLabel } from '../api/client'

// --- what the customer is claiming ----------------------------------------------------

interface ReasonCopy {
  short: string
  claim: string
  wins: string
}

const REASONS: Record<string, ReasonCopy> = {
  goods_not_received: {
    short: 'Never arrived',
    claim: 'Customer says the order never reached them.',
    wins: 'Delivery proof tying a person to an address — signature, OTP, or a matching ID.',
  },
  goods_not_as_described: {
    short: 'Not as described',
    claim: 'Customer says the item was not what was promised.',
    wins: 'The listing, inspection records, and any pre-purchase exchange about condition.',
  },
  duplicate_charge: {
    short: 'Charged twice',
    claim: 'Customer says they were billed twice for one purchase.',
    wins: 'Records showing the two charges are separate purchases.',
  },
  unrecognized_transaction: {
    short: 'Not my card',
    claim: 'Cardholder says they never authorised this.',
    wins: 'A known device, saved address, or prior account activity.',
  },
  subscription_cancelled: {
    short: 'Already cancelled',
    claim: 'Customer says they cancelled before this renewal.',
    wins: 'A cancellation timestamp after the billing date, plus the agreed terms.',
  },
  credit_not_processed: {
    short: 'Refund never came',
    claim: 'Customer says a promised refund never arrived.',
    wins: 'A settled refund reference, or the policy showing none was owed.',
  },
}

/** The reason codes the backend accepts, for the file-a-dispute form. */
export const REASON_CODES = Object.keys(REASONS)

export function reasonCopy(code: string): ReasonCopy {
  return (
    REASONS[code] ?? {
      short: code.replace(/_/g, ' '),
      claim: 'The cardholder is disputing this charge.',
      wins: 'Evidence addressing the specific assertion.',
    }
  )
}

// --- lifecycle stage ------------------------------------------------------------------

const PHASES: Record<string, { label: string; meaning: string }> = {
  fraud: { label: 'Fraud alert', meaning: 'Flagged as fraud. Not yet a chargeback.' },
  retrieval: { label: 'Info request', meaning: 'Documentation requested. Money not pulled.' },
  chargeback: { label: 'Chargeback', meaning: 'Money pulled back. Main window to fight.' },
  pre_arbitration: {
    label: 'Pre-arbitration',
    meaning: 'First representment rejected; issuer came back.',
  },
  arbitration: { label: 'Arbitration', meaning: 'Network decides. Fees highest, outcome final.' },
}

export function phaseCopy(phase: string) {
  return (
    PHASES[phase] ?? { label: phase.replace(/_/g, ' '), meaning: 'Dispute lifecycle stage.' }
  )
}

// --- what Coconut concluded -----------------------------------------------------------

interface RecommendationCopy {
  label: string
  headline: string
  action: string
  /** Semantic tone token — the only place colour enters the product. */
  tone: 'win' | 'warn' | 'risk' | 'mute'
}

/*
 * Role colours, per Addendum 4 (35.1): Support = emerald, Contradict = rose,
 * Neutral / Needs Human = amber, and slate for anything that needs no action.
 *
 * ACCEPT takes rose rather than amber because it is the CONTRADICT outcome wearing a
 * recommendation's clothes -- the evidence works against the merchant. Giving it amber
 * would collide with NEEDS_HUMAN_REVIEW and leave the banner unable to distinguish "the
 * evidence settles this against you" from "the evidence settles nothing", which are
 * opposite instructions to the person reading it.
 */
export const RECOMMENDATIONS: Record<Recommendation, RecommendationCopy> = {
  CONTEST: {
    label: 'Contest',
    headline: 'Worth fighting',
    action: 'Approve & prepare packet',
    tone: 'win',
  },
  ACCEPT: {
    label: 'Concede',
    headline: 'Not worth fighting',
    action: 'Approve — do not contest',
    tone: 'risk',
  },
  NEEDS_HUMAN_REVIEW: {
    label: 'Unclear',
    headline: 'Evidence does not settle it',
    action: 'Record my decision',
    tone: 'warn',
  },
  NO_ACTION_NEEDED: {
    label: 'No action',
    headline: 'NPCI will reject this for you',
    action: 'Acknowledge',
    tone: 'mute',
  },
}

// --- payment rails --------------------------------------------------------------------

const RAILS: Record<string, { label: string; meaning: string }> = {
  upi: {
    label: 'UPI',
    meaning: 'Clears through NPCI. Dispute caps and URCS auto-disposition apply.',
  },
  rupay: {
    label: 'RuPay',
    meaning: "Clears through NPCI's RGCS, with its own codes and timelines.",
  },
  card: { label: 'Card', meaning: 'Clears through Visa/Mastercard scheme rules.' },
}

export function railCopy(rail: string) {
  return RAILS[rail] ?? { label: rail.toUpperCase(), meaning: 'Settlement rail.' }
}

// --- per-evidence verdicts ------------------------------------------------------------

export const VERDICTS: Record<VerdictLabel, { label: string; tone: 'win' | 'risk' | 'mute' }> =
  {
    support: { label: 'Helps', tone: 'win' },
    contradict: { label: 'Hurts', tone: 'risk' },
    neutral: { label: 'Neutral', tone: 'mute' },
  }

// --- evidence types -------------------------------------------------------------------

const EVIDENCE_TYPES: Record<string, string> = {
  delivery_proof: 'Delivery proof',
  communication_log: 'Customer messages',
  device_signal: 'Device & session',
  order_history: 'Account history',
  other: 'Other',
}

export function evidenceLabel(type: string): string {
  return EVIDENCE_TYPES[type] ?? type.replace(/_/g, ' ')
}

// --- status ---------------------------------------------------------------------------

const STATUSES: Record<string, string> = {
  pending: 'Not assessed',
  decided: 'Awaiting you',
  approved: 'Approved',
  submitted: 'Packet logged',
}

export function statusLabel(
  status: string,
  recommendation?: Recommendation | null,
): string {
  if (status === 'decided') {
    if (recommendation === 'CONTEST') return 'Ready for approval'
    if (recommendation === 'ACCEPT') return 'Decision ready'
    if (recommendation === 'NEEDS_HUMAN_REVIEW') return 'Human review'
    if (recommendation === 'NO_ACTION_NEEDED') return 'Auto-resolved'
  }
  return STATUSES[status] ?? status
}
