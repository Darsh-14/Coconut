import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  formatPercent,
  type CalibrationResult,
  type GuaranteeVerification,
} from '../api/client'
import { Surface } from './ui'

/**
 * The risk budget dial (CLAUDE.md Addendum 3, Section 31).
 *
 * You do not pick a threshold; you pick the maximum contest-error rate you can live
 * with, and the prototype searches for an operating point whose corrected development
 * estimate clears it. A disjoint test split then reports what happened empirically. This
 * is deliberately not presented as a formal finite-sample or deployment guarantee.
 *
 * Deliberately plain: existing metric-card patterns, no new visual language, and the
 * numbers do not animate. The point is the claim, not the motion.
 */

// Wide enough to reach the achievable region. On this data the tightest supportable
// budget is around 71%, so a 1-20% slider (as first specified) would have had every
// position fail — which is a finding worth showing, not a range worth hiding behind.
const MIN_ALPHA = 1
const MAX_ALPHA = 90

async function calibrationAt(pct: number) {
  const calibration = await api.calibrate(pct / 100)
  const verified = await api.verifyGuarantee()
  return { calibration, verified }
}

export function RiskBudgetDial() {
  const [alpha, setAlpha] = useState(75)
  const [result, setResult] = useState<CalibrationResult | null>(null)
  const [verification, setVerification] = useState<GuaranteeVerification | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)

  const run = useCallback(async (pct: number) => {
    const ticket = ++seq.current
    setBusy(true)
    setError(null)
    try {
      const { calibration, verified } = await calibrationAt(pct)
      // A slower earlier request must not overwrite a newer one.
      if (ticket !== seq.current) return
      setResult(calibration)
      setVerification(verified)
    } catch (e) {
      if (ticket === seq.current) setError((e as Error).message)
    } finally {
      if (ticket === seq.current) setBusy(false)
    }
  }, [])

  useEffect(() => {
    let live = true
    const ticket = ++seq.current
    calibrationAt(75)
      .then(({ calibration, verified }) => {
        if (!live || ticket !== seq.current) return
        setResult(calibration)
        setVerification(verified)
      })
      .catch((e: Error) => {
        if (live && ticket === seq.current) setError(e.message)
      })
      .finally(() => {
        if (live && ticket === seq.current) setBusy(false)
      })
    return () => {
      live = false
    }
  }, [])

  const floor = result?.smallest_achievable_alpha ?? null

  return (
    <Surface className="overflow-hidden">
      <div className="p-5">
        <h2 className="text-[13px]" style={{ fontVariationSettings: "'wght' 590" }}>
          Risk-budget prototype
        </h2>
        <p className="mt-0.5 text-[12px] text-[var(--fg-3)]">
          Name the contest-error rate you can live with. The system searches for a
          threshold whose corrected development estimate is within it.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-4">
          <label className="flex min-w-64 flex-1 items-center gap-3">
            <span className="shrink-0 text-[12px] text-[var(--fg-2)]">
              Maximum contest-error rate
            </span>
            <input
              type="range"
              min={MIN_ALPHA}
              max={MAX_ALPHA}
              step={1}
              value={alpha}
              onChange={(e) => setAlpha(Number(e.target.value))}
              onMouseUp={() => run(alpha)}
              onKeyUp={() => run(alpha)}
              onTouchEnd={() => run(alpha)}
              className="min-w-40 flex-1 accent-[var(--fg)]"
              aria-label="Maximum contest-error rate I will accept"
            />
            <span
              className="num w-12 shrink-0 text-right text-[15px]"
              style={{ fontVariationSettings: "'wght' 560" }}
            >
              {alpha}%
            </span>
          </label>
          {busy && <span className="text-[11.5px] text-[var(--fg-3)]">calibrating…</span>}
        </div>

        {floor != null && (
          <p className="mt-2 text-[11px] text-[var(--fg-3)]">
            Tightest budget this calibration set can support:{' '}
            <span className="num">{formatPercent(floor)}</span>
          </p>
        )}
      </div>

      {error && (
        <p className="border-t px-5 py-3 text-[12.5px] text-[var(--risk)]" style={{ borderColor: 'var(--line)' }}>
          {error}
        </p>
      )}

      {result && (
        <>
          <div className="grid gap-px sm:grid-cols-3" style={{ background: 'var(--line)' }}>
            <Cell
              label="Calibrated threshold"
              value={result.achievable ? result.calibrated_threshold!.toFixed(2) : '—'}
              sub={
                result.achievable
                  ? `${result.n_above_threshold} of ${result.calibration_set_size} calibration cases`
                  : 'not achievable'
              }
            />
            <Cell
              label="Total resolution at this budget"
              value={verification ? formatPercent(verification.coverage) : '—'}
              sub={
                verification
                  ? `model decisions + NPCI rules · ${verification.n_test} held-out cases`
                  : 'awaiting verification'
              }
            />
            <Cell
              label="Observed contest error (test)"
              value={
                verification?.observed_fp_rate_on_test != null
                  ? formatPercent(verification.observed_fp_rate_on_test)
                  : '—'
              }
              sub={
                verification?.guarantee_held != null
                  ? verification.guarantee_held
                    ? 'empirical check passed'
                    : 'empirical check did NOT pass'
                  : verification
                    ? 'not evaluable: no model-contested cases'
                    : ''
              }
              tone={
                verification?.guarantee_held != null
                  ? verification.guarantee_held
                    ? 'win'
                    : 'risk'
                  : undefined
              }
            />
          </div>

          <p
            className="border-t px-5 py-3 text-[12.5px] leading-relaxed text-[var(--fg-2)]"
            style={{ borderColor: 'var(--line)' }}
          >
            {result.achievable && verification ? (
              <>
                At a {formatPercent(result.alpha)} contest-error budget the system resolves{' '}
                {formatPercent(verification.coverage)} through model decisions plus
                deterministic NPCI cap outcomes, and sends the rest to a person. On the
                held-out test split — never used to calibrate —{' '}
                {verification.observed_fp_rate_on_test != null ? (
                  <>
                    the observed contest-error rate was{' '}
                    {formatPercent(verification.observed_fp_rate_on_test)}.
                  </>
                ) : (
                  <>no model-contested cases made the statistic evaluable.</>
                )}
              </>
            ) : (
              <>
                A {formatPercent(result.alpha)} budget is not achievable on this
                calibration set
                {floor != null && <> — the tightest it supports is {formatPercent(floor)}</>}
                . Rather than pretend, the model defers every remaining case; deterministic
                NPCI cap outcomes still apply.
              </>
            )}
          </p>

          <p
            className="border-t px-5 py-3 text-[11px] leading-relaxed text-[var(--fg-3)]"
            style={{ borderColor: 'var(--line)' }}
          >
            {result.guarantee_statement} Calibration reuses synthetic development data;
            the threshold grid has no family-wise multiple-testing correction; and the
            measured risk is contest error among selected cases only, not recall or money
            recovered.
          </p>
        </>
      )}
    </Surface>
  )
}

function Cell({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub?: string
  tone?: 'win' | 'risk'
}) {
  return (
    <div className="p-4" style={{ background: 'var(--surface)' }}>
      <p className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">{label}</p>
      <p
        className="num mt-1.5 text-[27px] leading-none tracking-[-0.02em]"
        style={{
          fontVariationSettings: "'wght' 560",
          color: tone ? `var(--${tone})` : 'var(--fg)',
        }}
      >
        {value}
      </p>
      {sub && <p className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">{sub}</p>}
    </div>
  )
}
