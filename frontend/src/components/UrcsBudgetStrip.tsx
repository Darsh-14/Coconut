import { useEffect, useState } from 'react'
import { api, type URCSForecast } from '../api/client'
import { Surface } from './ui'

/**
 * NPCI's dispute budget for a UPI case.
 *
 * The point this makes visually: on UPI rails a real share of outcomes is decided by a
 * deterministic rules engine, not by anyone's judgement — so it is knowable in advance,
 * exactly. The counters are the whole argument, which is why they lead.
 *
 * `rules_verified_on` is rendered rather than hidden. NPCI has revised these rules three
 * times in two years, and a rules engine whose provenance is invisible is one nobody
 * should trust.
 */
export function UrcsBudgetStrip({ disputeId }: { disputeId: string }) {
  const [forecast, setForecast] = useState<URCSForecast | null>(null)

  useEffect(() => {
    let live = true
    api
      .urcsForecast(disputeId)
      .then((f) => live && setForecast(f))
      .catch(() => {
        /* the strip is supplementary; a failure here must not break the case page */
      })
    return () => {
      live = false
    }
  }, [disputeId])

  if (!forecast || forecast.predicted_disposition === 'UNKNOWN') return null

  const { budget } = forecast
  const rejecting = forecast.predicted_disposition === 'AUTO_REJECT'

  return (
    <Surface
      className="p-4"
      // Colour encodes state, as everywhere else: amber only when NPCI will reject.
      {...(rejecting
        ? { style: { boxShadow: 'var(--shadow-line), inset 2px 0 0 0 var(--warn)' } }
        : {})}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
            NPCI dispute budget
          </p>
          <p
            className="mt-1.5 text-[15px] tracking-[-0.015em]"
            style={{
              fontVariationSettings: "'wght' 560",
              color: rejecting ? 'var(--warn)' : 'var(--fg)',
            }}
          >
            {rejecting
              ? `URCS will auto-reject${forecast.predicted_reason_code ? ` — ${forecast.predicted_reason_code}` : ''}`
              : 'Within caps — proceeds to you'}
          </p>
        </div>

        <div className="flex gap-6">
          <Counter
            label="this payer"
            used={budget.customer_disputes_30d}
            cap={budget.customer_disputes_30d + budget.customer_cap_remaining}
            code="CD1"
          />
          <Counter
            label="with you"
            used={budget.payer_payee_disputes_30d}
            cap={budget.payer_payee_disputes_30d + budget.payer_payee_cap_remaining}
            code="CD2"
          />
        </div>
      </div>

      <p className="mt-3 text-[12px] leading-relaxed text-[var(--fg-2)]">
        {forecast.explanation}
      </p>

      {forecast.rgnb_re_raise_possible && (
        <p className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">
          The remitting bank may still re-raise this in good faith under RGNB.
        </p>
      )}

      <p className="mt-2.5 text-[11px] text-[var(--fg-3)]">
        Rules verified {forecast.rules_verified_on} against NPCI circulars · a rules engine,
        not a model
      </p>
    </Surface>
  )
}

function Counter({
  label,
  used,
  cap,
  code,
}: {
  label: string
  used: number
  cap: number
  code: string
}) {
  const spent = cap > 0 && used >= cap
  return (
    <div title={`${code}: ${used} of ${cap} in a rolling 30-day window`}>
      <p
        className="num text-[17px] leading-none tracking-[-0.02em]"
        style={{
          fontVariationSettings: "'wght' 560",
          color: spent ? 'var(--warn)' : 'var(--fg)',
        }}
      >
        {used}
        <span className="text-[var(--fg-3)]">/{cap}</span>
      </p>
      <p className="mt-1 text-[11px] text-[var(--fg-3)]">{label}</p>
    </div>
  )
}
