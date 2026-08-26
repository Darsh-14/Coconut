import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  api,
  countdownTo,
  formatInr,
  type DisputeStatus,
  type DisputeSummary,
} from '../api/client'
import { PhaseBadge, StatusBadge } from '../components/ConfidenceBadge'

const STATUS_FILTERS: Array<DisputeStatus | 'all'> = [
  'all',
  'pending',
  'decided',
  'approved',
  'submitted',
]

export default function DisputeQueue() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<DisputeSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<DisputeStatus | 'all'>('all')

  useEffect(() => {
    api
      .listDisputes()
      .then(setRows)
      .catch((e: Error) => setError(e.message))
  }, [])

  const visible = useMemo(
    () => (rows ?? []).filter((r) => filter === 'all' || r.status === filter),
    [rows, filter],
  )

  const urgentCount = useMemo(
    () => (rows ?? []).filter((r) => countdownTo(r.respond_by).urgent).length,
    [rows],
  )

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        {error}
      </div>
    )
  }

  if (!rows) return <p className="text-sm text-slate-500">Loading dispute queue…</p>

  return (
    <div>
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dispute queue</h1>
          <p className="mt-0.5 text-sm text-slate-600">
            {rows.length} open disputes
            {urgentCount > 0 && (
              <>
                {' · '}
                <span className="font-medium text-red-700">
                  {urgentCount} due within 48 hours
                </span>
              </>
            )}
          </p>
        </div>

        <div className="flex flex-wrap gap-1">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setFilter(s)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                filter === s
                  ? 'bg-slate-900 text-white'
                  : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </header>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full min-w-[52rem] text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Dispute</th>
              <th className="px-4 py-2 font-medium">Phase</th>
              <th className="px-4 py-2 font-medium">Reason</th>
              <th className="px-4 py-2 text-right font-medium">Amount</th>
              <th className="px-4 py-2 font-medium">Respond by</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {visible.map((row) => {
              const countdown = countdownTo(row.respond_by)
              return (
                <tr
                  key={row.dispute_id}
                  onClick={() => navigate(`/disputes/${row.dispute_id}`)}
                  className="cursor-pointer hover:bg-slate-50"
                >
                  <td className="px-4 py-2.5">
                    <span className="font-mono text-xs">
                      {row.dispute_id.replace('disp_synthetic_', '#')}
                    </span>
                    {row.payment_is_real && (
                      <span
                        className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800"
                        title={`Backed by real test-mode payment ${row.payment_id}`}
                      >
                        real payment
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <PhaseBadge phase={row.phase} />
                  </td>
                  <td className="px-4 py-2.5 text-slate-700">
                    {row.reason_code.replace(/_/g, ' ')}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums">
                    {formatInr(row.amount)}
                  </td>
                  <td
                    className={`px-4 py-2.5 font-medium ${
                      countdown.urgent ? 'text-red-700' : 'text-slate-600'
                    }`}
                  >
                    {countdown.label}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={row.status} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {visible.length === 0 && (
          <p className="p-6 text-center text-sm text-slate-500">
            No disputes with status “{filter}”.
          </p>
        )}
      </div>
    </div>
  )
}
