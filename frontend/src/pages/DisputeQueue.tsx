import { AlertTriangle, ChevronLeft, ChevronRight, Inbox, Search, SearchX } from 'lucide-react'
import { paths } from '../lib/routes'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  countdownTo,
  formatInr,
  parseApiDate,
  type DisputeSummary,
  type Recommendation,
} from '../api/client'
import { phaseCopy, railCopy, reasonCopy, RECOMMENDATIONS, statusLabel } from '../lib/labels'
import { useDisputes } from '../lib/useDisputes'
import { NewDisputeDialog } from '../components/NewDisputeDialog'
import {
  Badge,
  Button,
  EmptyState,
  PageHeader,
  Progress,
  Segmented,
  Surface,
  TableSkeleton,
} from '../components/ui'
import { toneDot } from '../components/uiTokens'

type Filter = 'all' | 'unassessed' | Recommendation
type SortKey = 'deadline' | 'amount'
const PAGE_SIZE = 25

export default function DisputeQueue() {
  const navigate = useNavigate()
  const { rows, error, stats, batch, assessNext, stopBatch, refresh, loading } = useDisputes()
  const [filing, setFiling] = useState(false)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<SortKey>('deadline')
  const [page, setPage] = useState(1)

  const filters = useMemo(
    () => [
      { key: 'all' as const, label: 'All', count: stats.total },
      { key: 'unassessed' as const, label: 'Unassessed', count: stats.unassessed },
      { key: 'CONTEST' as const, label: 'Contest', count: stats.contestCount },
      { key: 'ACCEPT' as const, label: 'Concede', count: stats.accept },
      { key: 'NEEDS_HUMAN_REVIEW' as const, label: 'Unclear', count: stats.review },
      { key: 'NO_ACTION_NEEDED' as const, label: 'No action', count: stats.noAction },
    ],
    [stats],
  )

  const visible = useMemo(() => {
    // Filtered here rather than round-tripping to the API: the whole queue is already
    // loaded for the counts above, so a request per keystroke would be slower and would
    // make the counts and the rows disagree mid-type. The API's own ?q= exists for
    // consumers that do not hold the list.
    const needle = search.trim().toLowerCase()
    const searched = needle
      ? (rows ?? []).filter(
          (r) =>
            r.dispute_id.toLowerCase().includes(needle) ||
            r.reason_code.toLowerCase().includes(needle) ||
            r.payment_id.toLowerCase().includes(needle) ||
            reasonCopy(r.reason_code).short.toLowerCase().includes(needle),
        )
      : (rows ?? [])
    const filtered = searched.filter((r) =>
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
  }, [rows, filter, sort, search])

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const pageRows = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  return (
    <div>
      {filing && (
        <NewDisputeDialog
          onClose={() => setFiling(false)}
          onFiled={(id) => {
            setFiling(false)
            void refresh()
            navigate(paths.dispute(id))
          }}
        />
      )}
      <PageHeader
        title="Disputes"
        sub={`${stats.total} open. Contesting costs ₹1,500 a case, win or lose.`}
        action={
          batch ? (
            <div className="w-full sm:w-52" aria-live="polite">
              <div className="flex items-baseline justify-between text-[11.5px]">
                <span className="text-[var(--fg-2)]">Assessing</span>
                <span className="num text-[var(--fg-3)]">
                  {batch.done}/{batch.total}
                </span>
              </div>
              <div className="mt-1.5">
                <Progress value={batch.done / batch.total} label="Dispute assessment progress" />
              </div>
              <button
                type="button"
                onClick={stopBatch}
                className="focus-ring mt-1.5 rounded text-[11.5px] text-[var(--fg-3)] hover:text-[var(--fg)]"
              >
                Stop
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {stats.unassessed > 0 && (
                <>
                  <Button onClick={() => assessNext(15)}>Assess 15</Button>
                  <Button onClick={() => assessNext(50)}>Assess 50</Button>
                </>
              )}
              <Button variant="primary" onClick={() => setFiling(true)}>
                File a dispute
              </Button>
            </div>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {/* Five filters do not fit a phone; let the strip scroll rather than the page. */}
        <div className="-mx-1 max-w-full overflow-x-auto px-1">
          <Segmented
            options={filters}
            value={filter}
            onChange={(next) => {
              setFilter(next)
              setPage(1)
            }}
            ariaLabel="Filter disputes"
            mode="filters"
          />
        </div>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <label className="relative min-w-0 flex-1 sm:flex-none">
            <span className="sr-only">Search disputes</span>
            <Search
              size={14}
              strokeWidth={1.7}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--fg-3)]"
              aria-hidden="true"
            />
            <input
              type="search"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(1)
              }}
              placeholder="Search id, reason, payment"
              className="focus-ring w-full rounded-[var(--radius-control)] bg-[var(--surface-2)] py-1.5 pl-8 pr-2.5 text-[12.5px] outline-none transition focus:bg-[var(--surface)] sm:w-60"
            />
          </label>
          <select
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as SortKey)
              setPage(1)
            }}
            className="surface focus-ring min-w-0 cursor-pointer px-2.5 py-1.5 text-[12.5px] text-[var(--fg-2)]"
            aria-label="Sort disputes"
          >
            <option value="deadline">Soonest deadline</option>
            <option value="amount">Largest amount</option>
          </select>
        </div>
      </div>

      {!loading && !error && visible.length > 0 && (
        <p className="mb-2 text-[11.5px] text-[var(--fg-3)]" aria-live="polite">
          {visible.length} {visible.length === 1 ? 'dispute' : 'disputes'} in this view
        </p>
      )}

      <Surface className="overflow-hidden">
        {error ? (
          <EmptyState
            icon={AlertTriangle}
            tone="risk"
            title="Could not load the queue"
            detail={error}
            action={<Button onClick={() => void refresh()}>Try again</Button>}
          />
        ) : loading ? (
          <TableSkeleton />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={search ? SearchX : Inbox}
            title={search ? `Nothing matches "${search}"` : 'Nothing in this view'}
            detail={
              search
                ? 'Try a dispute id, a payment id, or part of a reason.'
                : 'Change the filter above, or assess what is still pending.'
            }
            action={
              search ? (
                <Button
                  size="sm"
                  onClick={() => {
                    setSearch('')
                    setPage(1)
                  }}
                >
                  Clear search
                </Button>
              ) : stats.unassessed > 0 ? (
                <Button variant="primary" size="sm" onClick={() => assessNext(15)}>
                  Assess 15 disputes
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="divide-y divide-[var(--line)] md:hidden">
              {pageRows.map((row) => (
                <MobileCase key={row.dispute_id} row={row} />
              ))}
            </div>
            <div className="hidden overflow-x-auto md:block">
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
                  <th className="px-4 py-2.5 font-normal">Coconut</th>
                  <th className="px-4 py-2.5 font-normal">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line)]">
                {pageRows.map((row) => {
                  const countdown = countdownTo(row.respond_by)
                  const reason = reasonCopy(row.reason_code)
                  const rec = row.recommendation ? RECOMMENDATIONS[row.recommendation] : null
                  const noAction = row.recommendation === 'NO_ACTION_NEEDED'
                  return (
                    <tr
                      key={row.dispute_id}
                      onClick={() => navigate(paths.dispute(row.dispute_id))}
                      className={`cursor-pointer transition-colors duration-[160ms] hover:bg-[var(--surface-2)] ${
                        noAction ? 'opacity-55' : ''
                      }`}
                    >
                      <td className="px-4 py-3 align-middle">
                        {/* A real link, not just the row's onClick. The row handler is a
                            mouse convenience; without this the queue -- the app's primary
                            navigation -- was unreachable by keyboard entirely, and
                            middle-click to open a case in a new tab did nothing. */}
                        <Link
                          to={paths.dispute(row.dispute_id)}
                          onClick={(e) => e.stopPropagation()}
                          aria-label={`Open ${reason.short}, ${formatInr(row.amount)}, case ${row.dispute_id}`}
                          className="focus-ring num rounded text-[12px] text-[var(--fg-3)] transition hover:text-[var(--fg)]"
                        >
                          {row.dispute_id.replace('disp_synthetic_', '')}
                        </Link>
                        {row.payment_is_real && (
                          <span
                            className="ml-1.5 inline-block size-1.5 rounded-full align-middle"
                            style={{ background: 'var(--win)' }}
                            title={`Backed by a real test-mode payment (${row.payment_id})`}
                          />
                        )}
                      </td>

                      <td className="max-w-sm px-4 py-3 align-middle">
                        <div className="flex flex-wrap items-center gap-2">
                          <span style={{ fontVariationSettings: "'wght' 510" }}>
                            {reason.short}
                          </span>
                          <Badge title={phaseCopy(row.phase).meaning}>
                            {phaseCopy(row.phase).label}
                          </Badge>
                          <Badge title={railCopy(row.rail).meaning}>
                            {railCopy(row.rail).label}
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
                        {noAction ? (
                          <span
                            className="text-[12px] text-[var(--fg-3)]"
                            title="NPCI's URCS is expected to reject this without the merchant responding"
                          >
                            URCS will auto-reject
                            {row.urcs_reason_code && ` (${row.urcs_reason_code})`}
                          </span>
                        ) : rec ? (
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
            <QueuePagination
              page={currentPage}
              pages={pageCount}
              total={visible.length}
              onChange={setPage}
            />
          </>
        )}
      </Surface>
    </div>
  )
}

/** Phone layout: the same information hierarchy as the table without a sideways scroll. */
function MobileCase({ row }: { row: DisputeSummary }) {
  const countdown = countdownTo(row.respond_by)
  const reason = reasonCopy(row.reason_code)
  const recommendation = row.recommendation ? RECOMMENDATIONS[row.recommendation] : null
  const noAction = row.recommendation === 'NO_ACTION_NEEDED'

  return (
    <Link
      to={paths.dispute(row.dispute_id)}
      aria-label={`Open ${reason.short}, ${formatInr(row.amount)}, case ${row.dispute_id}`}
      className={`focus-ring pressable block p-4 transition-colors hover:bg-[var(--surface-2)] ${
        noAction ? 'opacity-65' : ''
      }`}
    >
      <span className="flex items-start justify-between gap-4">
        <span className="min-w-0">
          <span className="flex flex-wrap items-center gap-1.5">
            <span
              className="truncate text-[14px]"
              style={{ fontVariationSettings: "'wght' 560" }}
            >
              {reason.short}
            </span>
            <Badge title={phaseCopy(row.phase).meaning}>{phaseCopy(row.phase).label}</Badge>
            <Badge title={railCopy(row.rail).meaning}>{railCopy(row.rail).label}</Badge>
          </span>
          <span className="num mt-1.5 block text-[11px] text-[var(--fg-3)]">
            {row.dispute_id.replace('disp_synthetic_', '')}
            {row.payment_is_real && (
              <span className="ml-1.5 text-[var(--win)]" title="Backed by a real test-mode payment">
                • test payment
              </span>
            )}
          </span>
        </span>
        <span
          className="num shrink-0 text-[14px]"
          style={{ fontVariationSettings: "'wght' 560" }}
        >
          {formatInr(row.amount)}
        </span>
      </span>

      <span
        className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t pt-3"
        style={{ borderColor: 'var(--line)' }}
      >
        <span>
          <span className="block text-[10px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
            Due
          </span>
          <span
            className={`num mt-0.5 block text-[12px] ${
              countdown.urgent ? 'text-[var(--risk)]' : 'text-[var(--fg-2)]'
            }`}
          >
            {countdown.label}
          </span>
        </span>
        <span className="text-right">
          <span className="block text-[10px] uppercase tracking-[0.06em] text-[var(--fg-3)]">
            Coconut
          </span>
          <span className="mt-0.5 inline-flex items-center justify-end gap-1.5 text-[12px]">
            {noAction ? (
              <span className="text-[var(--fg-3)]">
                URCS auto-reject{row.urcs_reason_code && ` (${row.urcs_reason_code})`}
              </span>
            ) : recommendation ? (
              <>
                <span className={`size-1.5 shrink-0 rounded-full ${toneDot(recommendation.tone)}`} />
                <span style={{ fontVariationSettings: "'wght' 510" }}>
                  {recommendation.label}
                </span>
                {row.confidence != null && row.recommendation !== 'NEEDS_HUMAN_REVIEW' && (
                  <span className="num text-[var(--fg-3)]">
                    {(row.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </>
            ) : (
              <span className="text-[var(--fg-3)]">—</span>
            )}
          </span>
        </span>
        <span className="col-span-2 text-[11px] text-[var(--fg-3)]">
          {statusLabel(row.status)}
        </span>
      </span>
    </Link>
  )
}

function QueuePagination({
  page,
  pages,
  total,
  onChange,
}: {
  page: number
  pages: number
  total: number
  onChange: (page: number) => void
}) {
  if (pages <= 1) return null
  const start = (page - 1) * PAGE_SIZE + 1
  const end = Math.min(total, page * PAGE_SIZE)

  return (
    <nav
      className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3"
      style={{ borderColor: 'var(--line)' }}
      aria-label="Queue pages"
    >
      <p className="text-[11.5px] text-[var(--fg-3)]">
        Showing <span className="num">{start}–{end}</span> of{' '}
        <span className="num">{total}</span>
      </p>
      <span className="flex items-center gap-1.5">
        <Button
          variant="ghost"
          size="sm"
          disabled={page === 1}
          onClick={() => onChange(page - 1)}
          aria-label="Previous page"
        >
          <ChevronLeft size={14} aria-hidden="true" />
        </Button>
        <span className="num min-w-16 text-center text-[11.5px] text-[var(--fg-2)]">
          {page} / {pages}
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={page === pages}
          onClick={() => onChange(page + 1)}
          aria-label="Next page"
        >
          <ChevronRight size={14} aria-hidden="true" />
        </Button>
      </span>
    </nav>
  )
}
