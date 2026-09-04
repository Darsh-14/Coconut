/**
 * The demo session.
 *
 * DELIBERATELY NOT AN ACCOUNT SYSTEM, and it says so on the sign-in card itself.
 *
 * CLAUDE.md Section 16 puts authentication out of scope: this is a single-merchant demo,
 * so user accounts would be scope without signal. There is a second reason that matters
 * more in practice — a reviewer who meets a credential wall holding no credentials is
 * simply blocked, which is a worse outcome than having no sign-in at all.
 *
 * So this is a front door, not a gate. It records that someone chose to enter. No password
 * is checked, transmitted or stored; no API route is protected by it; there is no server
 * component. Anyone who wants the dashboard gets the dashboard.
 *
 * Naming that plainly in the UI is the point. A demo that quietly implied it authenticated
 * would be a small dishonesty inside a product whose entire argument is that it does not
 * overstate what it knows.
 */

const KEY = 'coconut.session'

export type Session = {
  merchant: string
  at: string
}

/**
 * localStorage throws rather than returning null in some contexts (Safari private mode,
 * browsers set to block site data). Every access is guarded so the app renders signed-out
 * instead of crashing on a storage policy it cannot control.
 */
function read(): Session | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Session>
    return parsed?.merchant ? { merchant: parsed.merchant, at: parsed.at ?? '' } : null
  } catch {
    return null
  }
}

export function currentSession(): Session | null {
  return read()
}

export function isSignedIn(): boolean {
  return read() !== null
}

export function signIn(merchant: string): Session {
  const session: Session = { merchant, at: new Date().toISOString() }
  try {
    localStorage.setItem(KEY, JSON.stringify(session))
  } catch {
    // Non-fatal: the session simply will not survive a reload. The gate is a front door,
    // so failing to persist it costs a re-click, not access.
  }
  return session
}

export function signOut(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* see above */
  }
}

/** The single merchant this demo represents. */
export const DEMO_MERCHANT = 'Kettle & Grain'
export const DEMO_EMAIL = 'risk@kettleandgrain.in'
