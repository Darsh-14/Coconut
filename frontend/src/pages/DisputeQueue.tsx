import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  api,
  countdownTo,
  formatInr,
  formatInrCompact,
  parseApiDate,
  type DisputeSummary,
  type Recommendation,
} from '../api/client'
import { phaseCopy, reasonCopy, RECOMMENDATIONS, statusLabel } from '../lib/labels'
import {
  Badge,
  Button,
  EmptyState,
  Metric,
  Progress,
  Surface,
  TableSkeleton,
  toneDot,
} from '../components/ui'

type Filter = 'all' | 'unassessed' | Recommendation
type SortKey = 'deadline' | 'amount'

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'unassessed', label: 'Unassessed' },
  { key: 'CONTEST', label: 'Contest' },
  { key: 'ACCEPT', label: 'Concede' },
  { key: 'NEEDS_HUMAN_REVIEW', label: 'Unclear' },
]

export default function DisputeQueue() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<DisputeSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<SortKey>('deadline')
  const [batch, setBatch] = useState<{ total: number; done: number } | null>(null)
  const cancelled = useRef(false)

  useEffect(() => {
    api
      .listDisputes()
      .then(setRows)
      .catch((e: Error) => setError(e.message))
  }, [])

  const stats = useMemo(() => {
    const all = rows ?? []
    const contest = all.filter((r) => r.recommendation === 'CONTEST')
    return {
      total: all.length,
      atRisk: all.reduce((s, r) => s + r.amount, 0),
      assessed: all.filter((r) => r.recommendation).length,
      contestCount: contest.length,
      contestValue: contest.reduce((s, r) => s + r.amount, 0),
      accept: all.filter((r) => r.recommendation === 'ACCEPT').length,
      review: all.filter((r) => r.recommendation === 'NEEDS_HUMAN_REVIEW').length,
      urgent: all.filter((r) => countdownTo(r.respond_by).urgent).length,
    }
  }, [rows])

  const visible = useMemo(() => {
    const filtered = (rows ?? []).filter((r) =>
      filter === 'all'
        ? true
        : filter === 'unassessed'
          ? !r.recommendation
          : r.recommendation === filter,
    )
    return [...filtered].sort((a, b) =>
      sort === 'amount'
        ? b.amount - a.amount
        : parseApiDate(a.respond_by).getTime() - parseApiDate(b.respond_by).getTime(),
    )
  }, [rows, filter, sort])

  /**
   * Assess a batch straight from the queue. Without it the app opens on 182 untouched
   * rows and nothing demonstrates that it does anything. Concurrency is 3; inference is
   * serialised server-side, so the win here is overlapping the drafting calls.
   */
  const assessNext = useCallback(
    async (n: number) => {
      const targets = (rows ?? []).filter((r) => !r.recommendation).slice(0, n)
      if (!targets.length) return

      cancelled.current = false
      setBatch({ total: targets.length, done: 0 })

      let cursor = 0
      const worker = async () => {
        while (!cancelled.current) {
          const i = cursor++
          if (i >= targets.length) return
          const target = targets[i]
          try {
            const decision = await api.decide(target.dispute_id)
            setRows((prev) =>
              prev?.map((r) =>
                r.dispute_id === target.dispute_id
                  ? {
                      ...r,
                      recommendation: decision.recommendation,
                      confidence: decision.confidence,
                      status: r.status === 'pending' ? 'decided' : r.status,
                    }
                  : r,
              ) ?? prev,
            )
          } catch {
            // Leave unassessed; progress still advances so a stall stays visible.
          }
          setBatch((b) => (b ? { ...b, done: b.done + 1 } : b))
        }
      }

      await Promise.all([worker(), worker(), worker()])
      setBatch(null)
    },
    [rows],
  )

  const unassessed = stats.total - stats.assessed
  const loading = !rows && !error

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] tracking-[-0.022em]" style={{ fontVariationSettings: "'wght' 590" }}>
            Disputes
          </h1>
          <p className="mt-1 text-[13px] text-[var(--fg-2)]">
            Contesting costs ₹1,500 per case, win or lose. Recourse reads the evidence and
            calls only what it can stand behind.
          </p>
        </div>

        {batch ? (
          <div className="w-56">
            <div className="flex items-baseline justify-between">
              <span className="text-[11.5px] text-[var(--fg-2)]">Assessing</span>
              <span className="num text-[11.5px] text-[var(--fg-3)]">
                {batch.done}/{batch.total}
              </span>
            </div>
            <div className="mt-1.5">
              <Progress value={batch.done / batch.total} />
            </div>
            <button
              type="button"
              onClick={() => {
                cancelled.current = true
              }}
              className="mt-1.5 text-[11.5px] text-[var(--fg-3)] hover:text-[var(--fg)]"
            >
              Stop
            </button>
          </div>
        ) : (
          unassessed > 0 && (
            <div className="flex gap-2">
              <Button variant="primary" onClick={() => assessNext(15)}>
                Assess 15
              </Button>
              <Button onClick={() => assessNext(50)}>Assess 50</Button>
            </div>
          )
        )}
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="In dispute"
          value={formatInrCompact(stats.atRisk)}
          sub={`${stats.total} open cases`}
          loading={loading}
        />
        <Metric
          label="Recoverable"
          value={stats.contestCount ? formatInrCompact(stats.contestValue) : '—'}
          sub={stats.contestCount ? `${stats.contestCount} to contest` : 'not yet assessed'}
          tone={stats.contestCount ? 'win' : undefined}
          loading={loading}
        />
        <Metric
          label="Assessed"
          value={`${stats.assessed}/${stats.total}`}
          sub={unassessed ? `${unassessed} remaining` : 'queue fully read'}
          loading={loading}
        />
        <Metric
          label="Due in 48h"
          value={String(stats.urgent)}
          sub="window closing"
          tone={stats.urgent ? 'risk' : undefined}
          loading={loading}
        />
      </div>

      {stats.assessed > 0 && (
        <SplitBar
          contest={stats.contestCount}
          accept={stats.accept}
          review={stats.review}
          total={stats.assessed}
        />
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((f) => {
            const count =
              f.key === 'all'
                ? stats.total
                : f.key === 'unassessed'
                  ? unassessed
                  : (rows ?? []).filter((r) => r.recommendation === f.key).length
            const active = filter === f.key
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={`rounded-[var(--radius-control)] px-2.5 py-1.5 text-[12.5px] transition duration-[160ms] ${
                  active
                    ? 'bg-[var(--fg)] text-[var(--bg)]'
                    : 'text-[var(--fg-2)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)]'
                }`}
                style={{ fontVariationSettings: "'wght' 510" }}
              >
                {f.label}
                <span className="num ml-1.5 opacity-55">{count}</span>
              </button>
            )
          })}
        </div>

        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="surface cursor-pointer px-2.5 py-1.5 text-[12.5px] text-[var(--fg-2)]"
          aria-label="Sort disputes"
        >
          <option value="deadline">Soonest deadline</option>
          <option value="amount">Largest amount</option>
        </select>
      </div>

      <Surface className="overflow-hidden">
        {error ? (
          <EmptyState title={error} />
        ) : loading ? (
          <TableSkeleton />
        ) : visible.length === 0 ? (
          <EmptyState
            title="Nothing here yet."
            action={
              unassessed > 0 ? (
                <Button variant="primary" size="sm" onClick={() => assessNext(15)}>
                  Assess 15 disputes
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[58rem] text-[13px]">
              <thead>
                <tr
                  className="border-b text-left text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]"
                  style={{ borderColor: 'var(--line)' }}
                >
                  <th className="px-4 py-2.5 font-normal">Case</th>
                  <th className="px-4 py-2.5 font-normal">Claim</th>
                  <th className="px-4 py-2.5 text-right font-normal">Amount</th>
                  <th className="px-4 py-2.5 font-normal">Due</th>
                  <th className="px-4 py-2.5 font-normal">Recourse</th>
                  <th className="px-4 py-2.5 font-normal">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: 'var(--line)' }}>
                {visible.map((row) => {
                  const countdown = countdownTo(row.respond_by)
                  const reason = reasonCopy(row.reason_code)
                  const rec = row.recommendation ? RECOMMENDATIONS[row.recommendation] : null
                  return (
                    <tr
                      key={row.dispute_id}
                      onClick={() => navigate(`/disputes/${row.dispute_id}`)}
                      className="cursor-pointer transition duration-[160ms] hover:bg-[var(--surface-2)]"
                    >
                      <td className="px-4 py-3 align-middle">
                        <span className="num text-[12px] text-[var(--fg-3)]">
                          {row.dispute_id.replace('disp_synthetic_', '')}
                        </span>
                        {row.payment_is_real && (
                          <span
                            className="ml-1.5 inline-block size-1.5 rounded-full bg-[var(--win)] align-middle"
                            title={`Backed by a real test-mode payment (${row.payment_id})`}
                          />
                        )}
                      </td>

                      <td className="max-w-sm px-4 py-3 align-middle">
                        <div className="flex items-center gap-2">
                          <span style={{ fontVariationSettings: "'wght' 510" }}>
                            {reason.short}
                          </span>
                          <Badge title={phaseCopy(row.phase).meaning}>
                            {phaseCopy(row.phase).label}
                          </Badge>
                        </div>
                      </td>

                      <td className="num px-4 py-3 text-right align-middle">
                        {formatInr(row.amount)}
                      </td>

                      <td className="px-4 py-3 align-middle">
                        <span
                          className={`num ${countdown.urgent ? 'text-[var(--risk)]' : 'text-[var(--fg-2)]'}`}
                        >
                          {countdown.label}
                        </span>
                      </td>

                      <td className="px-4 py-3 align-middle">
                        {rec ? (
                          <span className="inline-flex items-center gap-2">
                            <span className={`size-1.5 rounded-full ${toneDot(rec.tone)}`} />
                            <span style={{ fontVariationSettings: "'wght' 510" }}>
                              {rec.label}
                            </span>
                            {row.confidence != null &&
                              row.recommendation !== 'NEEDS_HUMAN_REVIEW' && (
                                <span className="num text-[11.5px] text-[var(--fg-3)]">
                                  {(row.confidence * 100).toFixed(0)}%
                                </span>
                              )}
                          </span>
                        ) : (
                          <span className="text-[var(--fg-3)]">—</span>
                        )}
                      </td>

                      <td className="px-4 py-3 align-middle text-[var(--fg-2)]">
                        {statusLabel(row.status)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Surface>
    </div>
  )
}

/** How the assessed portion split. One line, no explanation. */
function SplitBar({
  contest,
  accept,
  review,
  total,
}: {
  contest: number
  accept: number
  review: number
  total: number
}) {
  const pct = (n: number) => `${(n / total) * 100}%`
  const legend = [
    { label: 'Contest', n: contest, tone: 'bg-[var(--win)]' },
    { label: 'Concede', n: accept, tone: 'bg-[var(--warn)]' },
    { label: 'Unclear', n: review, tone: 'bg-[var(--accent)]' },
  ]
  return (
    <Surface className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
      <div className="flex h-1.5 min-w-40 flex-1 overflow-hidden rounded-full bg-[var(--surface-3)]">
        <div className="bg-[var(--win)] transition-[width] duration-500" style={{ width: pct(contest) }} />
        <div className="bg-[var(--warn)] transition-[width] duration-500" style={{ width: pct(accept) }} />
        <div className="bg-[var(--accent)] transition-[width] duration-500" style={{ width: pct(review) }} />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {legend.map((l) => (
          <span key={l.label} className="flex items-center gap-1.5 text-[12px] text-[var(--fg-2)]">
            <span className={`size-1.5 rounded-full ${l.tone}`} />
            {l.label}
            <span className="num text-[var(--fg)]" style={{ fontVariationSettings: "'wght' 560" }}>
              {l.n}
            </span>
          </span>
        ))}
      </div>
    </Surface>
  )
}
