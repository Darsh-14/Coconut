import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { paths } from '../lib/routes'

import { DemoContext, useDemo } from '../lib/demo'

export function DemoProvider({ children }: { children: React.ReactNode }) {
  const [demo, setDemo] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/workspace', { signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(data => setDemo(data?.demo === true))
      .catch(() => {})
    return () => controller.abort()
  }, [])
  return <DemoContext.Provider value={demo}>{children}</DemoContext.Provider>
}

export function DemoWorkspace() {
  const demo = useDemo()
  const [scenarios, setScenarios] = useState<{ id: string; label: string }[]>([])
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!demo) return
    const controller = new AbortController()
    fetch('/api/demo/scenarios', { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('Could not load demo cases.')
        return response.json()
      }).then(data => setScenarios(data.scenarios))
      .catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [demo])
  if (!demo) return null
  async function reset() {
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/demo/reset', { method: 'POST' })
      if (!response.ok) throw new Error('Reset failed. Try again.')
      window.location.assign(paths.overview)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reset failed.')
      setBusy(false)
    }
  }
  return <section aria-label="Demo workspace" className="border-b border-[var(--line)] px-4 py-3 sm:px-8">
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <span className="rounded bg-[var(--surface-3)] px-2 py-1 font-medium">Demo</span>
      {scenarios.map(scenario => <Link key={scenario.id} to={paths.dispute(scenario.id)} className="focus-ring rounded text-[var(--fg-2)] hover:text-[var(--fg)]">{scenario.label}</Link>)}
      <button className="focus-ring ml-auto rounded text-[var(--fg-3)]" onClick={() => setConfirm(true)}>Reset demo</button>
    </div>
    <p className="mt-2 text-xs text-[var(--fg-3)]">Sample cases · Real assessments · Simulated submission</p>
    {confirm && <div className="mt-3 flex flex-wrap items-center gap-3 text-xs" role="alert">
      <span>Clear this demo's edits and approvals?</span>
      <button className="focus-ring rounded text-[var(--risk)]" disabled={busy} onClick={() => void reset()}>{busy ? 'Resetting…' : 'Confirm reset'}</button>
      <button className="focus-ring rounded" disabled={busy} onClick={() => setConfirm(false)}>Cancel</button>
    </div>}
    {error && <p className="mt-2 text-xs text-[var(--risk)]" role="alert">{error}</p>}
  </section>
}
