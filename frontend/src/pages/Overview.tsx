import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  countdownTo,
  formatInr,
  formatInrCompact,
  parseApiDate,
  type DisputeSummary,
} from '../api/client'
import { reasonCopy, RECOMMENDATIONS } from '../lib/labels'
import { useDisputes } from '../lib/useDisputes'
import {
  BigFigure,
  Button,
  CaseRow,
  PageHeader,
  Progress,
  Skeleton,
  Surface,
  toneDot,
} from '../components/ui'

export default function Overview() {
  const navigate = useNavigate()
  const { rows, error, stats, batch, assessNext, stopBatch, loading } = useDisputes()

  const urgent = useMemo(
    () =>
      [...(rows ?? [])]
        .filter((r) => countdownTo(r.respond_by).urgent)
        .sort((a, b) => parseApiDate(a.respond_by).getTime() - parseApiDate(b.respond_by).getTime())
        .slice(0, 5),
    [rows],
  )

  const contestable = useMemo(
    () =>
      [...(rows ?? [])]
        .filter((r) => r.recommendation === 'CONTEST')
        .sort((a, b) => b.amount - a.amount)
        .slice(0, 5),
    [rows],
  )

  return (
    <div>
      <PageHeader
        title="Overview"
        sub="Where the money is, and what Recourse would do about it."
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
              <Button variant="primary" onClick={() => assessNext(25)}>
                Assess {Math.min(25, stats.unassessed)} disputes
              </Button>
            )
          )
        }
      />

      {error && (
        <Surface className="p-5 text-[13px] text-[var(--risk)]">{error}</Surface>
      )}

      {!error && (
        <div className="space-y-4">
          {/* --- the hero figure ------------------------------------------------- */}
          <Surface className="overflow-hidden">
            <div className="grid gap-8 p-7 sm:grid-cols-[auto_1fr] sm:items-center">
              <BigFigure
                value={formatInrCompact(stats.atRisk)}
                label={`at stake across ${stats.total} open disputes`}
                loading={loading}
              />

              <div className="grid grid-cols-2 gap-6 sm:grid-cols-3">
                <Inline
                  value={stats.contestCount ? formatInrCompact(stats.contestValue) : '—'}
                  label="worth contesting"
                  tone="win"
                  loading={loading}
                />
                <Inline
                  value={stats.urgent ? formatInrCompact(stats.urgentValue) : '—'}
                  label="due within 48h"
                  tone={stats.urgent ? 'risk' : undefined}
                  loading={loading}
                />
                <Inline
                  value={`${stats.assessed}/${stats.total}`}
                  label="assessed"
                  loading={loading}
                />
              </div>
            </div>

            {stats.assessed > 0 && (
              <Split
                contest={stats.contestCount}
                accept={stats.accept}
                review={stats.review}
                total={stats.assessed}
              />
            )}
          </Surface>

          {/* --- the two shortlists ---------------------------------------------- */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title="Closing soonest"
              hint={stats.urgent ? `${stats.urgent} under 48h` : undefined}
              onAll={() => navigate('/disputes')}
              loading={loading}
              empty="Nothing urgent."
            >
              {urgent.map((r) => {
                const c = countdownTo(r.respond_by)
                return (
                  <CaseRow
                    key={r.dispute_id}
                    id={r.dispute_id.replace('disp_synthetic_', '')}
                    title={reasonCopy(r.reason_code).short}
                    meta={formatInr(r.amount)}
                    right={
                      <span className="num text-[12.5px] text-[var(--risk)]">{c.label}</span>
                    }
                    onClick={() => navigate(`/disputes/${r.dispute_id}`)}
                  />
                )
              })}
            </Panel>

            <Panel
              title="Ready to contest"
              hint={stats.contestCount ? `${stats.contestCount} cases` : undefined}
              onAll={() => navigate('/disputes')}
              loading={loading}
              empty={
                stats.assessed
                  ? 'None of the assessed cases clear the bar.'
                  : 'Assess the queue to populate this.'
              }
            >
              {contestable.map((r) => (
                <CaseRow
                  key={r.dispute_id}
                  id={r.dispute_id.replace('disp_synthetic_', '')}
                  title={reasonCopy(r.reason_code).short}
                  meta={
                    <span className="flex items-center gap-1.5">
                      <span className={`size-1.5 rounded-full ${toneDot('win')}`} />
                      {RECOMMENDATIONS.CONTEST.label}
                      {r.confidence != null && (
                        <span className="num">{(r.confidence * 100).toFixed(0)}%</span>
                      )}
                    </span>
                  }
                  right={<span className="num text-[12.5px]">{formatInr(r.amount)}</span>}
                  onClick={() => navigate(`/disputes/${r.dispute_id}`)}
                />
              ))}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <ExposureByReason rows={rows ?? []} loading={loading} />
            <ModelCard onOpen={() => navigate('/metrics')} />
          </div>
        </div>
      )}
    </div>
  )
}

/** Where the exposure actually sits. A merchant asks this before asking anything else. */
function ExposureByReason({
  rows,
  loading,
}: {
  rows: DisputeSummary[]
  loading: boolean
}) {
  const buckets = useMemo(() => {
    const by = new Map<string, { value: number; count: number }>()
    for (const r of rows) {
      const k = r.reason_code
      const b = by.get(k) ?? { value: 0, count: 0 }
      b.value += r.amount
      b.count += 1
      by.set(k, b)
    }
    return [...by.entries()]
      .map(([code, b]) => ({ code, ...b }))
      .sort((a, b) => b.value - a.value)
  }, [rows])

  const max = buckets[0]?.value ?? 1

  return (
    <Surface className="p-4">
      <h2 className="mb-3 px-2.5 text-[13px]" style={{ fontVariationSettings: "'wght' 590" }}>
        Exposure by dispute type
      </h2>
      {loading ? (
        <div className="space-y-2 px-2.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-7 w-full" />
          ))}
        </div>
      ) : (
        <ul className="space-y-2 px-2.5 pb-1">
          {buckets.map((b) => (
            <li key={b.code}>
              <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
                <span>{reasonCopy(b.code).short}</span>
                <span className="flex items-baseline gap-2">
                  <span className="num text-[11px] text-[var(--fg-3)]">{b.count}</span>
                  <span className="num" style={{ fontVariationSettings: "'wght' 540" }}>
                    {formatInrCompact(b.value)}
                  </span>
                </span>
              </div>
              <div
                className="mt-1 h-1 overflow-hidden rounded-full"
                style={{ background: 'var(--surface-3)' }}
              >
                <div
                  className="h-full rounded-full transition-[width] duration-500 ease-[var(--ease-snap)]"
                  style={{ width: `${(b.value / max) * 100}%`, background: 'var(--fg-3)' }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Surface>
  )
}

/**
 * The recorded held-out result, surfaced on the landing page. Figures match README.md's
 * table and the Performance page; labelled as a recorded run, never as a live one.
 */
function ModelCard({ onOpen }: { onOpen: () => void }) {
  return (
    <Surface className="flex flex-col p-5">
      <h2 className="text-[13px]" style={{ fontVariationSettings: "'wght' 590" }}>
        How well it calls them
      </h2>
      <p className="mt-1 text-[11.5px] text-[var(--fg-3)]">
        Last recorded run, 79 held-out disputes.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <Inline value="62.5%" label="precision when it says contest" />
        <Inline value="21.5%" label="of the queue it will call" />
      </div>

      <p className="mt-4 text-[11.5px] leading-relaxed text-[var(--fg-3)]">
        It abstains on four cases in five. That is the design — guessing is what costs a
        merchant the ₹1,500 twice over.
      </p>

      <Button className="mt-4 w-full" onClick={onOpen}>
        See the full evaluation
      </Button>
    </Surface>
  )
}

// --- pieces ---------------------------------------------------------------------------

function Inline({
  value,
  label,
  tone,
  loading,
}: {
  value: string
  label: string
  tone?: 'win' | 'risk'
  loading?: boolean
}) {
  return (
    <div>
      {loading ? (
        <Skeleton className="h-6 w-16" />
      ) : (
        <p
          className="num text-[21px] leading-none tracking-[-0.025em]"
          style={{
            fontVariationSettings: "'wght' 570",
            color: tone ? `var(--${tone})` : 'var(--fg)',
          }}
        >
          {value}
        </p>
      )}
      <p className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">{label}</p>
    </div>
  )
}

function Split({
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
    { label: 'Contest', n: contest, v: 'win' },
    { label: 'Concede', n: accept, v: 'warn' },
    { label: 'Unclear', n: review, v: 'accent' },
  ]
  return (
    <div className="border-t px-7 py-4" style={{ borderColor: 'var(--line)' }}>
      <div className="flex h-1.5 overflow-hidden rounded-full" style={{ background: 'var(--surface-3)' }}>
        {legend.map((l) => (
          <div
            key={l.label}
            className="transition-[width] duration-500 ease-[var(--ease-snap)]"
            style={{ width: pct(l.n), background: `var(--${l.v})` }}
          />
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1">
        {legend.map((l) => (
          <span key={l.label} className="flex items-center gap-1.5 text-[11.5px] text-[var(--fg-2)]">
            <span className="size-1.5 rounded-full" style={{ background: `var(--${l.v})` }} />
            {l.label}
            <span className="num" style={{ fontVariationSettings: "'wght' 570" }}>
              {l.n}
            </span>
          </span>
        ))}
        <span className="ml-auto text-[11px] text-[var(--fg-3)]">
          of {total} read
        </span>
      </div>
    </div>
  )
}

function Panel({
  title,
  hint,
  onAll,
  loading,
  empty,
  children,
}: {
  title: string
  hint?: string
  onAll: () => void
  loading?: boolean
  empty: string
  children: React.ReactNode
}) {
  const items = Array.isArray(children) ? children : [children]
  const isEmpty = !loading && items.flat().filter(Boolean).length === 0

  return (
    <Surface className="p-4">
      <div className="mb-2 flex items-baseline justify-between gap-2 px-2.5">
        <h2 className="text-[13px]" style={{ fontVariationSettings: "'wght' 590" }}>
          {title}
        </h2>
        <div className="flex items-baseline gap-3">
          {hint && <span className="text-[11.5px] text-[var(--fg-3)]">{hint}</span>}
          <button
            type="button"
            onClick={onAll}
            className="text-[11.5px] text-[var(--accent)] hover:underline"
          >
            All
          </button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2 px-2.5">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : isEmpty ? (
        <p className="px-2.5 py-8 text-center text-[12.5px] text-[var(--fg-3)]">{empty}</p>
      ) : (
        <div className="space-y-0.5">{children}</div>
      )}
    </Surface>
  )
}
