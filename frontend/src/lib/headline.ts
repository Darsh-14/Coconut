/**
 * The numbers shown on the landing page.
 *
 * Held static rather than fetched, for two reasons. The landing page renders before the
 * dashboard and must not look broken when the API is cold — a marketing surface that
 * shows a spinner or an error is worse than one that shows a dated figure. And these are
 * a specific recorded run against the held-out split, not a live reading: labelling them
 * with the date they were produced is the honest presentation.
 *
 * Regenerate with:  python eval/run_evaluation.py     (from backend/)
 * Then update this file and the results table in README.md together — they drifted apart
 * once already, which is exactly the failure this comment exists to prevent.
 */
export const HEADLINE = {
  precision: '0.692',
  recall: '0.750',
  f1: '0.720',
  coverage: '0.291',
  falsePositiveCostInr: 6000,
  nEvaluated: 79,
  autoResolved: 5,
  /** ISO date of the run these came from. */
  measuredOn: '2026-08-28',
} as const
