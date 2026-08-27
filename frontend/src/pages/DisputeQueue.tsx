import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  countdownTo,
  formatInr,
  parseApiDate,
  type Recommendation,
} from '../api/client'
import { phaseCopy, reasonCopy, RECOMMENDATIONS, statusLabel } from '../lib/labels'
import { useDisputes } from '../lib/useDisputes'
import {
  Badge,
  Button,
  EmptyState,
  PageHeader,
  Progress,
  Segmented,
  Surface,
  TableSkeleton,
  toneDot,
} from '../components/ui'

type Filter = 'all' | 'unassessed' | Recommendation
type SortKey = 'deadline' | 'amount'

export default function DisputeQueue() {
  const navigate = useNavigate()
  const { rows, error, stats, batch, assessNext, stopBatch, loading } = useDisputes()
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<SortKey>('deadline')

  const filters = useMemo(
    () => [
      { key: 'all' as const, label: 'All', count: stats.total },
      { key: 'unassessed' as const, label: 'Unassessed', count: stats.unassessed },
      { key: 'CONTEST' as const, label: 'Contest', count: stats.contestCount },
      { key: 'ACCEPT' as const, label: 'Concede', count: stats.accept },
      { key: 'NEEDS_HUMAN_REVIEW' as const, label: 'Unclear', count: stats.review },
    ],
    [stats],
  )

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

  return (
    <div>
      <PageHeader
        title="Disputes"
        sub={`${stats.total} open. Contesting costs ₹1,500 a case, win or lose.`}
        action={
          batch ? (
            <div className="w-52">
              <div className="flex items-baseline justify-between text-[11.5px]">
                <span className="text-[var(--fg-2)]">Assessing</span>
                <span className="num text-[var(--fg-3)]">
                  {batch.done}/{batch.total}
                </span>
              </div>
              <div className="mt-1.5">
                <Progress value={batch.done / batch.total} />
              </div>
              <button
                type="button"
                onClick={stopBatch}
                className="mt-1.5 text-[11.5px] text-[var(--fg-3)] hover:text-[var(--fg)]"
              >
                Stop
              </button>
            </div>
          ) : (
            stats.unassessed > 0 && (
              <div className="flex gap-2">
                <Button variant="primary" onClick={() => assessNext(15)}>
                  Assess 15
                </Button>
                <Button onClick={() => assessNext(50)}>Assess 50</Button>
              </div>
            )
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {/* Five filters do not fit a phone; let the strip scroll rather than the page. */}
        <div className="-mx-1 max-w-full overflow-x-auto px-1">
          <Segmented options={filters} value={filter} onChange={setFilter} />
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
            title="Nothing in this view."
            action={
              stats.unassessed > 0 ? (
                <Button variant="primary" size="sm" onClick={() => assessNext(15)}>
                  Assess 15 disputes
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[56rem] text-[13px]">
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
                      className="cursor-pointer transition-colors duration-[160ms] hover:bg-[var(--surface-2)]"
                    >
                      <td className="px-4 py-3 align-middle">
                        <span className="num text-[12px] text-[var(--fg-3)]">
                          {row.dispute_id.replace('disp_synthetic_', '')}
                        </span>
                        {row.payment_is_real && (
                          <span
                            className="ml-1.5 inline-block size-1.5 rounded-full align-middle"
                            style={{ background: 'var(--win)' }}
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
