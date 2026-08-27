import { useState } from 'react'
import { api, type DisputePhase, type PaymentRail } from '../api/client'
import { Dialog, DialogBody, DialogFooter, DialogHeader } from './Dialog'
import { Button } from './ui'
import { phaseCopy, railCopy, REASON_CODES, reasonCopy } from '../lib/labels'

/**
 * File a dispute by hand.
 *
 * Until this existed the queue was a fixed seed loaded from a committed JSON file — the
 * app could only ever show what shipped inside it, which is most of why it read as a
 * prototype. This is the write path.
 *
 * Amount is entered in rupees and sent in paise. Everything downstream stores paise, and
 * asking a merchant to type 349900 for ₹3,499 would be a good way to collect wrong data.
 */

const PHASES: DisputePhase[] = ['fraud', 'retrieval', 'chargeback', 'pre_arbitration', 'arbitration']
const RAILS: PaymentRail[] = ['upi', 'rupay', 'card']

export function NewDisputeDialog({
  onClose,
  onFiled,
}: {
  onClose: () => void
  onFiled: (disputeId: string) => void
}) {
  const [reasonCode, setReasonCode] = useState(REASON_CODES[0])
  const [claimText, setClaimText] = useState('')
  const [rupees, setRupees] = useState('')
  const [phase, setPhase] = useState<DisputePhase>('chargeback')
  const [rail, setRail] = useState<PaymentRail>('upi')
  const [payerRef, setPayerRef] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const amount = Math.round(Number(rupees) * 100)
  const amountValid = Number.isFinite(amount) && amount > 0
  const claimValid = claimText.trim().length >= 10
  const canSubmit = amountValid && claimValid && !busy

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const dispute = await api.createDispute({
        reason_code: reasonCode,
        claim_text: claimText.trim(),
        amount,
        phase,
        rail,
        payer_ref: rail === 'upi' && payerRef.trim() ? payerRef.trim() : null,
      })
      onFiled(dispute.dispute_id)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <Dialog labelledBy="new-dispute-title" onClose={onClose} width="max-w-xl">
      <DialogHeader
        id="new-dispute-title"
        title="File a dispute"
        sub="Assess it once it's in the queue."
        onClose={onClose}
      />

      <DialogBody>
        <div className="space-y-4 p-5">
          <Field label="What is the customer claiming?">
            <select
              value={reasonCode}
              onChange={(e) => setReasonCode(e.target.value)}
              className={inputClass}
            >
              {REASON_CODES.map((code) => (
                <option key={code} value={code}>
                  {reasonCopy(code).short}
                </option>
              ))}
            </select>
            <p className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">
              {reasonCopy(reasonCode).claim}
            </p>
          </Field>

          <Field label="The bank's wording">
            <textarea
              value={claimText}
              onChange={(e) => setClaimText(e.target.value)}
              rows={4}
              placeholder="Cardholder asserts the merchandise was never delivered to the address on file."
              className={`${inputClass} resize-y`}
            />
            {claimText.length > 0 && !claimValid && (
              <p className="mt-1.5 text-[11.5px] text-[var(--risk)]">
                Needs at least 10 characters.
              </p>
            )}
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Amount (₹)">
              <input
                type="number"
                inputMode="decimal"
                min="1"
                step="1"
                value={rupees}
                onChange={(e) => setRupees(e.target.value)}
                placeholder="3499"
                className={`num ${inputClass}`}
              />
              {rupees && !amountValid && (
                <p className="mt-1.5 text-[11.5px] text-[var(--risk)]">
                  Must be more than zero.
                </p>
              )}
            </Field>

            <Field label="Stage">
              <select
                value={phase}
                onChange={(e) => setPhase(e.target.value as DisputePhase)}
                className={inputClass}
              >
                {PHASES.map((p) => (
                  <option key={p} value={p}>
                    {phaseCopy(p).label}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Rail">
              <select
                value={rail}
                onChange={(e) => setRail(e.target.value as PaymentRail)}
                className={inputClass}
              >
                {RAILS.map((r) => (
                  <option key={r} value={r}>
                    {railCopy(r).label}
                  </option>
                ))}
              </select>
            </Field>

            {/* Only UPI has NPCI cap counters to key on, so this is asked only there. */}
            {rail === 'upi' && (
              <Field label="Payer reference">
                <input
                  value={payerRef}
                  onChange={(e) => setPayerRef(e.target.value)}
                  placeholder="payer_0001"
                  className={`num ${inputClass}`}
                />
                <p className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">
                  Used for the NPCI 30-day cap counters.
                </p>
              </Field>
            )}
          </div>

          <p className="text-[11px] leading-relaxed text-[var(--fg-3)]">
            Filed disputes exist only inside Recourse. Like the seeded ones they can never
            reach Razorpay's live dispute workflow. Evidence is attached on the case page
            afterwards.
          </p>

          {error && <p className="text-[12px] text-[var(--risk)]">{error}</p>}
        </div>
      </DialogBody>

      <DialogFooter>
        <span className="text-[11.5px] text-[var(--fg-3)]">
          {amountValid ? `₹${(amount / 100).toLocaleString('en-IN')}` : 'Enter an amount'}
        </span>
        <div className="flex gap-2">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={!canSubmit}>
            {busy ? 'Filing…' : 'File dispute'}
          </Button>
        </div>
      </DialogFooter>
    </Dialog>
  )
}

const inputClass =
  'w-full rounded-[var(--radius-control)] bg-[var(--surface-2)] px-3 py-2 text-[13px] text-[var(--fg)] outline-none transition focus:bg-[var(--surface)] focus:shadow-[var(--shadow-line)]'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
        {label}
      </span>
      {children}
    </label>
  )
}
