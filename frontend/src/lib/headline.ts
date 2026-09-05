/**
 * THE RECORDED EVALUATION RUN — one definition, read by every surface that quotes it.
 *
 * Three surfaces used to carry these figures as independent literals: the landing page,
 * the Overview's "How well it calls them" card, and the Performance page. They drifted,
 * and how they drifted is the reason this file exists rather than three sets of numbers.
 *
 * Current figures belong here; explicitly historical baselines live separately below.
 * UI pages derive their displayed counts from this object rather than repeating literals.
 *
 * Held static rather than fetched, deliberately: the landing page renders before the API
 * is warm, and a marketing surface showing a spinner or an error is worse than one showing
 * a dated figure. These are a specific recorded run, and are labelled as one everywhere
 * they appear — never as a live reading.
 *
 * Regenerate with `python eval/run_evaluation.py` from backend/, then update this file and
 * README.md's results table together. scripts/landing-ui.mjs asserts the landing page
 * still agrees with these, including the confusion matrix.
 */

/** Current synthetic held-out run of the shipped NLI pipeline plus CONTEST safety gate. */
export const RECORDED = {
  precision: 1,
  recall: 0.6667,
  f1: 0.8,
  coverage: 0.2025,
  selectiveAccuracy: 0.8125,
  populationAutoWinCapture: 0.1875,
  contestSupport: 6,
  precisionWilson95: { lower: 0.6097, upper: 1 },
  falsePositiveCostInr: 0,
  nEvaluated: 79,
  autoResolved: 0,
  matrix: { tp: 6, fp: 0, fn: 3, tn: 7, flagged_human: 63 },
  /** ISO date of the run these figures came from. */
  measuredOn: '2026-09-05',
} as const

/** What the shipped operating point is compared against on the Performance page. */
export const BASELINES = {
  /** Same regenerated held-out set and NLI decisions before the learned gate. */
  ungatedCurrent: { precision: 0.7143, coverage: 0.3038 },
  /** Section 10's hand-picked 0.7 / 0.65 thresholds, before calibration replaced them. */
  section10: { precision: 0.625, coverage: 0.215 },
  /** The single-signal engine, rejected: worse than a coin flip, and inverted. */
  naive: { precision: 0.481, coverage: 0.423 },
} as const

/** The share genuinely handed to a person; model coverage excludes NPCI rule outcomes. */
export const HUMAN_REVIEW_RATE = RECORDED.matrix.flagged_human / RECORDED.nEvaluated

/**
 * Pre-formatted to three decimals, so no two surfaces round the same number differently.
 */
export const HEADLINE = {
  precision: RECORDED.precision.toFixed(3),
  recall: RECORDED.recall.toFixed(3),
  f1: RECORDED.f1.toFixed(3),
  coverage: RECORDED.coverage.toFixed(3),
  falsePositiveCostInr: RECORDED.falsePositiveCostInr,
  nEvaluated: RECORDED.nEvaluated,
  autoResolved: RECORDED.autoResolved,
  measuredOn: RECORDED.measuredOn,
} as const
