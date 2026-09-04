import { useCallback, useState } from 'react'
import { api, formatInr, type BackingStatus } from '../api/client'
import { Button } from './ui'

/**
 * Attach a genuine test-mode Razorpay payment to a dispute (CLAUDE.md Section 7).
 *
 * Section 7 wants each dispute's payment_id to reference a real test-mode payment, and
 * most seeded disputes still carry a pay_PENDING_ placeholder. That is not an oversight:
 * Razorpay has no endpoint that fabricates a payment, and this account has
 * server-to-server payment creation disabled, so the only route to a real pay_... id is
 * the one an actual merchant integration uses — a real order, and a human completing
 * Checkout against it.
 *
 * So this component does the part software can do and stops where a person is required,
 * which is the same shape as the approve flow: the system prepares, a human acts.
 *
 * The payment id is read back off the order server-side rather than taken from Checkout's
 * browser callback. That is deliberate — the callback is client-controlled, and a claim
 * this app makes loudly ("backed by a real payment") should rest on Razorpay's own record,
 * not on what the page reported about itself.
 */

const CHECKOUT_SRC = 'https://checkout.razorpay.com/v1/checkout.js'

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void }
  }
}

/** Load Checkout once, and reuse it on later attempts. */
function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve()
  const existing = document.querySelector<HTMLScriptElement>(`script[src="${CHECKOUT_SRC}"]`)
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener('load', () => resolve())
      existing.addEventListener('error', () => reject(new Error('Checkout failed to load')))
    })
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = CHECKOUT_SRC
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Could not reach Razorpay Checkout'))
    document.body.appendChild(script)
  })
}

export function BackingPayment({
  disputeId,
  amount,
  onAttached,
}: {
  disputeId: string
  amount: number
  onAttached: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<BackingStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  const settle = useCallback(async () => {
    const result = await api.backingStatus(disputeId)
    setStatus(result)
    if (result.payment_is_real) onAttached()
  }, [disputeId, onAttached])

  const start = useCallback(async () => {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const order = await api.createBackingOrder(disputeId)
      await loadCheckout()
      if (!window.Razorpay) throw new Error('Checkout did not initialise')

      const checkout = new window.Razorpay({
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        order_id: order.order_id,
        name: 'Coconut',
        description: order.description,
        // Both paths ask the server what actually happened rather than trusting the
        // browser: success may still need confirming, and a dismissal may follow a
        // payment that did go through.
        handler: () => void settle().finally(() => setBusy(false)),
        modal: { ondismiss: () => void settle().finally(() => setBusy(false)) },
        notes: { purpose: 'coconut-synthetic-dispute-backing', dispute_id: disputeId },
        theme: { color: '#4f46e5' },
      })
      checkout.open()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }, [disputeId, settle])

  return (
    <div>
      <Button className="w-full" onClick={start} disabled={busy}>
        {busy ? 'Waiting for checkout…' : 'Attach a real test payment'}
      </Button>
      <p className="mt-2 text-[11px] leading-relaxed text-[var(--fg-3)]">
        Opens Razorpay Checkout in test mode for {formatInr(amount)}. No real money moves.
        Completing it replaces the placeholder id with a genuine payment.
      </p>
      {status && !status.payment_is_real && (
        <p className="mt-2 text-[11px] text-[var(--warn)]">{status.message}</p>
      )}
      {status?.payment_is_real && (
        <p className="mt-2 text-[11px] text-[var(--win)]">{status.message}</p>
      )}
      {error && <p className="mt-2 text-[11px] text-[var(--risk)]">{error}</p>}
    </div>
  )
}
