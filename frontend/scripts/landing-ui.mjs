// Optional front-door smoke test: the landing page, the sign-in gate, and the /app move.
//
// Companion to smoke-ui.mjs (the decision loop) and a11y-ui.mjs (keyboard + responsive),
// kept separate for the same reason -- it needs Playwright plus a ~115MB browser download,
// which would work against the repo's "clone and run in five minutes" goal. With the
// backend and Vite dev server both running:
//
//   npm install && npx playwright install chromium
//   npm run verify:landing
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

const BASE = process.env.BASE_URL ?? 'http://localhost:5173'
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

// The landing figures must match the last evaluation run. Recall and F1 came off the page
// when the copy was tightened, so they are no longer asserted -- but the confusion matrix
// is on the page, and it is a stricter guard than the ratios were: the counts have to
// agree with each other as well as with the run.
const body = await page.locator('body').innerText()
for (const [n, what] of [
  ['1.000', 'precision'],
  ['0.203', 'coverage'],
  ['79', 'held-out record count'],
  ['0', 'false-positive cost'],
])
  check(body.includes(n), `landing shows the measured ${what} (${n})`)

// Read the matrix out of the table structurally rather than regexing the page text: the
// hero contains the word "OTP", which a naive /TP\s+9/ would happily match.
const matrix = await page.evaluate(() => {
  const table = [...document.querySelectorAll('table')].find((t) =>
    t.textContent.includes('deferred rather than guessed'),
  )
  if (!table) return null
  return [...table.querySelectorAll('tbody tr')].map((tr) =>
    [...tr.children].slice(0, 2).map((cell) => cell.textContent.trim()),
  )
})
check(matrix !== null, 'the confusion matrix table is present')
for (const [k, v] of [['TP', '6'], ['FP', '0'], ['FN', '3'], ['TN', '7'], ['Human', '63'], ['URCS', '0']])
  check(
    Boolean(matrix?.some((row) => row[0] === k && row[1] === v)),
    `confusion matrix ${k} = ${v}`,
  )

// Scroll the whole page: the screenshots below the fold are lazy, and the reveal only
// resolves as content comes within the fold.
await page.evaluate(async () => {
  for (let y = 0; y < document.body.scrollHeight; y += 500) {
    window.scrollTo(0, y)
    await new Promise((r) => setTimeout(r, 40))
  }
})
await page.waitForTimeout(700)

// Nothing may be left invisible. An earlier IntersectionObserver version stranded 4 of 37
// elements after a single instant jump -- blank bands, permanently, for that visitor.
const stranded = await page.evaluate(
  () => [...document.querySelectorAll('.reveal')].filter((e) => getComputedStyle(e).opacity !== '1').length,
)
check(stranded === 0, `no revealed element is left invisible (${stranded} stranded)`)

// The hero's confidence bar animates from scaleX(0). If the keyframe stops resolving it
// would sit at zero width forever -- invisible, and silently deleting the one number the
// hero exists to show.
await page.evaluate(() => window.scrollTo(0, 0))
await page.waitForTimeout(900)
const meter = await page.evaluate(() => {
  const el = document.querySelector('.meter-fill')
  return el ? Math.round(el.getBoundingClientRect().width) : -1
})
check(meter > 10, `the hero confidence bar has real width (${meter}px)`)

// The product screenshots are real files; a 404 renders as a broken image, not an error.
const shots = await page.evaluate(() =>
  [...document.querySelectorAll('img[src^="/shots/"]')]
    .filter((i) => getComputedStyle(i).display !== 'none')
    .map((i) => ({ src: i.getAttribute('src'), ok: i.complete && i.naturalWidth > 0 })),
)
check(shots.length === 3, `three product screenshots are shown (${shots.length})`)
check(shots.every((s) => s.ok), 'every product screenshot loaded', JSON.stringify(shots.filter((s) => !s.ok)))
await page.evaluate(() => window.scrollTo(0, 0))

// section arrangement, in order
const heads = await page.locator('main h2').allInnerTexts()
console.log('        sections:', heads.map(h => h.trim()).join(' | '))
check(heads.length >= 6, `landing has ${heads.length} sections`)

// --- 2. gate: deep link bounces to login, then returns -------------------------------
await page.goto(`${BASE}/app/disputes`, { waitUntil: 'networkidle' })
check(page.url().endsWith('/login'), 'unauthenticated deep link redirects to /login', page.url())

// --- 3. sign in ---------------------------------------------------------------------
check(await page.getByRole('heading', { name: 'Open demo workspace' }).isVisible(), 'demo entry is explicit')
check(await page.locator('input[type="password"]').count() === 0, 'demo does not collect a password')
check((await page.locator('body').innerText()).includes('No server authentication'),
      'demo entry states the authentication limitation')
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

// --- 4b. the same numbers everywhere ---------------------------------------------------
// These figures once lived as literals on three surfaces and drifted. They now share
// lib/headline.ts; this asserts they still agree.
await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
await page.getByText('at stake across').waitFor({ timeout: 30000 })
const modelCard = await page
  .locator('text=How well it calls them')
  .locator('xpath=ancestor::*[contains(@class,"surface")][1]')
  .innerText()
check(modelCard.includes('100.0%'), 'Overview quotes the shipped precision (100.0%)', modelCard.slice(0, 90))
check(modelCard.includes('20.3%'), 'Overview quotes the shipped coverage (20.3%)')
check(!modelCard.includes('62.5%') && !modelCard.includes('21.5%'),
      'Overview does not quote the hand-picked thresholds as the recorded run')

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
