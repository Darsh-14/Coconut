// Optional front-door smoke test: the landing page, the sign-in gate, and the /app move.
//
// Companion to smoke-ui.mjs (the decision loop) and a11y-ui.mjs (keyboard + responsive),
// kept separate for the same reason -- it needs Playwright plus a ~115MB browser download,
// which would work against the repo's "clone and run in five minutes" goal. With the
// backend and Vite dev server both running:
//
//   npm i -D playwright && npx playwright install chromium
//   node scripts/landing-ui.mjs
//
// What it guards, and why each check is here:
//
//   * The landing page must show the SAME held-out numbers the README and the evaluation
//     report. They are static in lib/headline.ts, so nothing but a test stops them drifting
//     from the run they came from -- which is exactly how the README's own prose drifted.
//   * The dashboard moved from / to /app when the front door arrived. Every internal link
//     had to move with it; a missed one is a dead link a reviewer finds before I do.
//   * The gate must let a deep link through after sign-in rather than dumping the visitor
//     on the overview, and must not re-gate on reload.
//
import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const errors = []
let pass = 0, fail = 0
const check = (ok, label, detail = '') => {
  if (ok) { pass++; console.log(`  PASS  ${label}`) }
  else { fail++; console.log(`  FAIL  ${label}${detail ? ' :: ' + detail : ''}`) }
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
page.on('pageerror', e => errors.push('pageerror: ' + e.message))

// --- 1. landing renders at the root -------------------------------------------------
await page.goto(BASE, { waitUntil: 'networkidle' })
check(await page.locator('h1').first().isVisible(), 'landing h1 renders')
console.log('        h1:', (await page.locator('h1').first().innerText()).replace(/\s+/g, ' '))
check(!(await page.locator('aside').count()), 'landing has no dashboard sidebar')

// the measured numbers must be the real ones
const body = await page.locator('body').innerText()
for (const n of ['0.692', '0.750', '0.720', '0.291', '79'])
  check(body.includes(n), `landing shows measured ${n}`)

// section arrangement, in order
const heads = await page.locator('main h2').allInnerTexts()
console.log('        sections:', heads.map(h => h.trim()).join(' | '))
check(heads.length >= 6, `landing has ${heads.length} sections`)

// --- 2. gate: deep link bounces to login, then returns -------------------------------
await page.goto(`${BASE}/app/disputes`, { waitUntil: 'networkidle' })
check(page.url().endsWith('/login'), 'unauthenticated deep link redirects to /login', page.url())

// --- 3. sign in ---------------------------------------------------------------------
check(await page.locator('#email').isVisible(), 'login shows an email field')
check((await page.locator('body').innerText()).includes('not an account system'),
      'login states it is not an account system')
await page.locator('button[type=submit]').click()
await page.waitForURL('**/app/disputes', { timeout: 5000 }).catch(() => {})
check(page.url().includes('/app/disputes'), 'sign-in returns to the originally requested page', page.url())

// --- 4. the dashboard loop still works ----------------------------------------------
await page.waitForSelector('table tbody tr', { timeout: 15000 })
const rows = await page.locator('table tbody tr').count()
check(rows > 0, `queue renders ${rows} rows`)

const caseLink = page.locator('table tbody a[href^="/app/disputes/disp"]').first()
check((await caseLink.count()) > 0, 'case links carry the /app prefix')
const href = await caseLink.getAttribute('href')
await caseLink.click()
await page.waitForURL(`**${href}`, { timeout: 5000 })
// Assert the exact path, not a substring: a link whose href and destination disagree is
// precisely the failure a prefix move introduces, and `includes` would not catch it.
check(new URL(page.url()).pathname === href, 'the case link lands on exactly its href', page.url())
await page.waitForSelector('h1, h2', { timeout: 10000 })

// back to queue via the in-page link
await page.locator('a[href="/app/disputes"]').first().click()
await page.waitForURL('**/app/disputes', { timeout: 5000 })
check(page.url().endsWith('/app/disputes'), 'back-link returns to the queue')

// --- 5. nav ---------------------------------------------------------------------------
await page.locator('aside a[href="/app/metrics"]').click()
await page.waitForURL('**/app/metrics', { timeout: 5000 })
check(page.url().endsWith('/app/metrics'), 'sidebar reaches Performance')

// --- 6. session survives a reload, and sign-out works ---------------------------------
await page.reload({ waitUntil: 'networkidle' })
check(page.url().endsWith('/app/metrics'), 'session survives a reload (no bounce to /login)', page.url())

await page.locator('aside button[aria-label="Sign out"]').click()
await page.waitForURL(BASE + '/', { timeout: 5000 }).catch(() => {})
check(new URL(page.url()).pathname === '/', 'sign-out returns to the landing page', page.url())

await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
check(page.url().endsWith('/login'), 'after sign-out the dashboard is gated again', page.url())

// --- 7. responsive --------------------------------------------------------------------
for (const w of [1280, 1024, 900]) {
  const p = await browser.newPage({ viewport: { width: w, height: 900 } })
  await p.goto(BASE, { waitUntil: 'networkidle' })
  const overflow = await p.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)
  check(overflow <= 0, `landing has no horizontal overflow at ${w}px`, `overflow ${overflow}px`)
  await p.close()
}

console.log(`\n  console errors: ${errors.length}`)
errors.forEach(e => console.log('    ' + e))
console.log(`\n  ${pass} passed, ${fail} failed`)
await browser.close()
process.exit(fail || errors.length ? 1 : 0)
