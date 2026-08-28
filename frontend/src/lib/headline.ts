/**
 * THE RECORDED EVALUATION RUN — one definition, read by every surface that quotes it.
 *
 * Three surfaces used to carry these figures as independent literals: the landing page,
 * the Overview's "How well it calls them" card, and the Performance page. They drifted,
 * and how they drifted is the reason this file exists rather than three sets of numbers.
 *
 * Overview showed 62.5% precision at 21.5% coverage under the heading "Last recorded run",
 * and its own docstring claimed those matched the README and the Performance page. They
 * did not. Those are Section 10's HAND-PICKED thresholds, not the calibrated ones the
 * system actually ships with. A reviewer moving from the landing page (0.692) to the
 * dashboard (0.625) would have found the product contradicting itself about its own
 * accuracy — in a project whose entire argument is honest measurement.
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

/** The shipped operating point: conformal-calibrated thresholds, on the held-out split. */
export const RECORDED = {
  precision: 0.692,
  recall: 0.75,
  f1: 0.72,
  coverage: 0.291,
  falsePositiveCostInr: 6000,
  nEvaluated: 79,
  autoResolved: 5,
  matrix: { tp: 9, fp: 4, fn: 3, tn: 7, flagged_human: 51 },
  /** ISO date of the run these figures came from. */
  measuredOn: '2026-08-28',
} as const

/** What the shipped operating point is compared against on the Performance page. */
export const BASELINES = {
  /** Section 10's hand-picked 0.7 / 0.65 thresholds, before calibration replaced them. */
  section10: { precision: 0.625, coverage: 0.215 },
  /** The single-signal engine, rejected: worse than a coin flip, and inverted. */
  naive: { precision: 0.481, coverage: 0.423 },
} as const

/** The share of the queue handed back to a person rather than decided. */
export const ABSTAIN_RATE = 1 - RECORDED.coverage

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
