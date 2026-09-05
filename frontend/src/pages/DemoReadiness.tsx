import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type DisputeSummary } from '../api/client'
import { Button, PageHeader, Surface } from '../components/ui'
import { paths } from '../lib/routes'

type Readiness = { ready: boolean; model_loaded: boolean; calibrated: boolean; database: string }
const OUTCOMES = [
  ['CONTEST', 'Contest'], ['ACCEPT', 'Accept'],
  ['NEEDS_HUMAN_REVIEW', 'Human review'], ['NO_ACTION_NEEDED', 'UPI auto-reject'],
] as const

export default function DemoReadiness() {
  const [status, setStatus] = useState<Readiness | null>(null)
  const [cases, setCases] = useState<DisputeSummary[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const activeRequest = useRef<AbortController | null>(null)
  const refresh = useCallback(async () => {
    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    try {
      const [response, rows] = await Promise.all([fetch('/api/ready', { signal: controller.signal }), api.listDisputes(controller.signal)])
      if (!response.ok && response.status !== 503) throw new Error(`Readiness check failed (${response.status})`)
      const data = await response.json() as Readiness
      if (activeRequest.current !== controller) return
      setStatus(data)
      setCases(rows)
      setError('')
    } catch (e) {
      if (activeRequest.current !== controller) return
      setStatus(null)
      setCases([])
      setError(controller.signal.aborted ? 'Readiness check timed out. Try again when the service is available.' : e instanceof Error ? e.message : 'Unable to check readiness')
    } finally {
      window.clearTimeout(timeout)
      if (activeRequest.current === controller) setBusy(false)
    }
  }, [])
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- refresh updates state only after its requests settle.
    const frame = window.requestAnimationFrame(() => void refresh())
    return () => {
      window.cancelAnimationFrame(frame)
      activeRequest.current?.abort()
      activeRequest.current = null
    }
  }, [refresh])
  const backed = cases.find((row) => row.payment_is_real)
  return <div className="space-y-5">
    <PageHeader title="Demo readiness" sub="Live checks for the presentation workspace." action={<Button disabled={busy} onClick={() => { setBusy(true); void refresh() }}>{busy ? 'Checking…' : 'Refresh checks'}</Button>} />
    {error && <p role="alert" className="text-sm text-[var(--risk)]">{error}</p>}
    <Surface className="p-5">
      <h2 className="mb-3 text-sm font-medium">Service status</h2>
      <dl className="grid gap-3 text-sm sm:grid-cols-3" aria-live="polite">
        {[
          ['NLI model', status?.model_loaded ? 'Loaded' : 'Not ready'],
          ['Calibration', status?.calibrated ? 'Available' : 'Not ready'],
          ['Database', status?.database === 'ok' ? 'Connected' : 'Not ready'],
        ].map(([label, value]) => <div key={label}><dt className="text-xs text-[var(--fg-3)]">{label}</dt><dd className="mt-1">{status ? value : 'Not checked'}</dd></div>)}
      </dl>
    </Surface>
    <Surface className="p-5">
      <h2 className="mb-3 text-sm font-medium">Presentation cases</h2>
      <ul className="divide-y divide-[var(--line)]">
        {OUTCOMES.map(([key, label]) => {
          const row = cases.find((r) => r.recommendation === key && (key !== 'NO_ACTION_NEEDED' || r.rail === 'upi'))
          return <li key={key} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"><span>{label}</span>{row ? <Link className="focus-ring rounded text-[var(--accent)]" to={paths.dispute(row.dispute_id)}>Open case →</Link> : <span className="text-xs text-[var(--fg-3)]">Assessment needed</span>}</li>
        })}
      </ul>
      <p className="mt-3 text-xs text-[var(--fg-3)]">Open each case to check evidence freshness and approval state before presenting.</p>
    </Surface>
    <Surface className="space-y-2 p-5 text-sm">
      <h2 className="font-medium">Razorpay backing</h2>
      {backed ? <Link className="focus-ring inline-block rounded text-[var(--accent)]" to={paths.dispute(backed.dispute_id)}>Inspect attached test payment →</Link> : <p className="text-[var(--fg-2)]">No attached test payment found. Complete Checkout on a case to attach one.</p>}
      <p className="text-xs text-[var(--fg-3)]">An attached ID is stored locally. Verify it through Razorpay before claiming a completed integration.</p>
    </Surface>
    <p className="text-xs text-[var(--fg-3)]">Demo access is stored in this browser. API requests have no server authentication. Use a controlled local environment.</p>
  </div>
}
