import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, countdownTo, type DisputeSummary } from '../api/client'

export interface QueueStats {
  total: number
  atRisk: number
  assessed: number
  unassessed: number
  contestCount: number
  contestValue: number
  accept: number
  review: number
  noAction: number
  urgent: number
  urgentValue: number
}

export interface BatchProgress {
  total: number
  done: number
}

/**
 * The queue, its derived figures, and batch assessment.
 *
 * Lives in a hook because Overview and Disputes are now separate pages that need the same
 * data and the same action — duplicating the fetch and the worker pool across both would
 * drift the moment either changed.
 */
export function useDisputes() {
  const [rows, setRows] = useState<DisputeSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [batch, setBatch] = useState<BatchProgress | null>(null)
  const cancelled = useRef(false)

  useEffect(() => {
    let live = true
    api
      .listDisputes()
      .then((r) => live && setRows(r))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [])

  const stats: QueueStats = useMemo(() => {
    const all = rows ?? []
    const contest = all.filter((r) => r.recommendation === 'CONTEST')
    const urgent = all.filter((r) => countdownTo(r.respond_by).urgent)
    const assessed = all.filter((r) => r.recommendation).length
    return {
      total: all.length,
      atRisk: all.reduce((s, r) => s + r.amount, 0),
      assessed,
      unassessed: all.length - assessed,
      contestCount: contest.length,
      contestValue: contest.reduce((s, r) => s + r.amount, 0),
      accept: all.filter((r) => r.recommendation === 'ACCEPT').length,
      review: all.filter((r) => r.recommendation === 'NEEDS_HUMAN_REVIEW').length,
      noAction: all.filter((r) => r.recommendation === 'NO_ACTION_NEEDED').length,
      urgent: urgent.length,
      urgentValue: urgent.reduce((s, r) => s + r.amount, 0),
    }
  }, [rows])

  /**
   * Assess the next n unassessed disputes. Concurrency is 3: inference is serialised
   * server-side behind the tokenizer lock, so the win is overlapping the drafting calls
   * that CONTEST cases make.
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

  const stopBatch = useCallback(() => {
    cancelled.current = true
  }, [])

  return {
    rows,
    error,
    stats,
    batch,
    assessNext,
    stopBatch,
    loading: !rows && !error,
  }
}
