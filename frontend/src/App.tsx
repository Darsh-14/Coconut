import { useEffect, useState } from 'react'

type Health = {
  status: string
  version: string
  razorpay_mode: string
  razorpay_key_id_prefix: string
  anthropic_configured: boolean
  auto_submit_to_razorpay: boolean
}

/**
 * Phase 0 placeholder shell.
 *
 * Its only job is to prove the Vite dev server boots and can reach the FastAPI backend
 * through the /api proxy. Phase 7 replaces this with the router and the three real pages
 * (DisputeQueue, CaseDetail, MetricsDashboard).
 */
export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <main className="mx-auto max-w-2xl p-10">
      <h1 className="text-3xl font-semibold tracking-tight">Recourse</h1>
      <p className="mt-1 text-slate-600">Explainable chargeback defense copilot</p>

      <section className="mt-8 rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-medium uppercase tracking-wide text-slate-500">
          Backend connection
        </h2>

        {error && (
          <p className="mt-3 text-sm text-red-700">
            Cannot reach the backend ({error}). Start it with{' '}
            <code className="rounded bg-slate-100 px-1">uvicorn app.main:app --reload</code> from{' '}
            <code className="rounded bg-slate-100 px-1">backend/</code>.
          </p>
        )}

        {!error && !health && <p className="mt-3 text-sm text-slate-500">Checking…</p>}

        {health && (
          <dl className="mt-3 grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-slate-500">Status</dt>
            <dd className="font-medium text-green-700">{health.status}</dd>
            <dt className="text-slate-500">API version</dt>
            <dd className="font-mono">{health.version}</dd>
            <dt className="text-slate-500">Razorpay mode</dt>
            <dd className="font-medium">{health.razorpay_mode}</dd>
            <dt className="text-slate-500">Key</dt>
            <dd className="font-mono">{health.razorpay_key_id_prefix}…</dd>
            <dt className="text-slate-500">Auto-submit</dt>
            <dd className="font-medium">
              {health.auto_submit_to_razorpay ? 'enabled' : 'disabled (human approval required)'}
            </dd>
          </dl>
        )}
      </section>

      <p className="mt-6 text-xs text-slate-500">
        Phase 0 scaffold. Dispute queue, case detail, and metrics dashboard land in Phase 7.
      </p>
    </main>
  )
}
