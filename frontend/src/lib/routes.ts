/**
 * Every internal path in one place.
 *
 * The dashboard moved off the origin root to /app when the landing and sign-in pages took
 * over the front door. Centralising the paths made that a single edit rather than a hunt
 * through a dozen call sites, and it keeps the router, the components and the Playwright
 * scripts reading from one definition instead of three copies that drift.
 */
export const paths = {
  landing: '/',
  login: '/login',
  overview: '/app',
  disputes: '/app/disputes',
  dispute: (id: string) => `/app/disputes/${id}`,
  metrics: '/app/metrics',
  readiness: '/app/readiness',
  review: '/app/disputes?filter=NEEDS_HUMAN_REVIEW',
  upi: '/app/disputes?rail=upi',
} as const

/** The prefix the authenticated shell is mounted under. */
export const APP_PREFIX = '/app'
