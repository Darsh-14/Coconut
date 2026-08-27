// Optional accessibility and responsive smoke test (CLAUDE.md Addendum 4, 35.2.3):
// keyboard navigability across textareas and modal dialogs, the responsive boundaries at
// desktop (1280px+) and laptop (1024px), and that an explicit light choice still works.
//
// Companion to smoke-ui.mjs, and kept separate for the same reason: it needs Playwright
// plus a ~115MB browser download, which would work against the repo's "clone and run in
// five minutes" goal. With the backend and Vite dev server both running:
//
//   npm i -D playwright && npx playwright install chromium
//   node scripts/a11y-ui.mjs
//
// Every check here started as a real defect. The queue was mouse-only until a case link
// existed; dialogs opening on a skeleton left focus outside themselves; and the focus ring
// applied unconditionally rather than on :focus-visible, so every control wore one at rest.
import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const SHOTS = process.env.SHOTS_DIR ?? './.shots'
const browser = await chromium.launch()

// The dashboard now sits behind a front door (pages/Login.tsx), so every page these
// scripts open needs a session in localStorage or it lands on /login instead. The gate is
// a UI convenience with no server component -- see lib/session.ts -- so seeding it here is
// exactly what a signed-in reviewer's browser holds, not a bypass of anything.
const SESSION = JSON.stringify({ merchant: 'Kettle & Grain', at: new Date().toISOString() })
async function newPage(opts) {
  const p = await browser.newPage(opts)
  await p.addInitScript((s) => localStorage.setItem('recourse.session', s), SESSION)
  return p
}
const errors = []
const ok = (c, m) => {
  console.log(`${c ? 'PASS' : 'FAIL'}  ${m}`)
  if (!c) process.exitCode = 1
}

const page = await newPage({ viewport: { width: 1440, height: 1000 } })
page.on('console', (m) => m.type() === 'error' && errors.push(m.text().slice(0, 140)))
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))

const rows = await (await page.request.get('http://127.0.0.1:8000/disputes')).json()
const target = rows[0].dispute_id

// --- Tab reaches every control -------------------------------------------
await page.goto(`${BASE}/app/disputes`, { waitUntil: 'networkidle' })
await page.locator('table tbody tr').first().waitFor({ timeout: 30000 })

const reached = new Set()
for (let i = 0; i < 25; i++) {
  await page.keyboard.press('Tab')
  const tag = await page.evaluate(() => {
    const el = document.activeElement
    return el ? `${el.tagName}:${el.getAttribute('aria-label') ?? el.textContent?.trim().slice(0, 18) ?? ''}` : ''
  })
  if (tag) reached.add(tag)
}
ok(reached.size > 6, `Tab reaches ${reached.size} distinct controls on the queue`)
ok(
  [...reached].some((t) => t.startsWith('INPUT')),
  'the search field is keyboard reachable',
)

// --- Enter activates a row -----------------------------------------------
await page.goto(`${BASE}/app/disputes`, { waitUntil: 'networkidle' })
await page.locator('table tbody tr').first().waitFor({ timeout: 30000 })
const caseLink = page.locator('table tbody a[href^="/app/disputes/disp"]').first()
await caseLink.waitFor({ timeout: 10000 })
await caseLink.focus()
ok(
  await page.evaluate(() => document.activeElement?.tagName === 'A'),
  'a case is reachable by keyboard from the queue',
)
await page.keyboard.press('Enter')
await page.waitForURL(/\/disputes\/disp/, { timeout: 10000 })
ok(true, 'Enter opens the case')

// --- Escape closes a dialog ----------------------------------------------
await page.goto(`${BASE}/app/disputes/${target}`, { waitUntil: 'networkidle' })
await page.getByText(/Bank.s claim/).waitFor({ timeout: 20000 })
await page.locator('button[title="Open the record behind this evidence"]').first().click()
await page.locator('[role="dialog"]').waitFor({ timeout: 10000 })

const focusInDialog = await page.evaluate(
  () => !!document.activeElement?.closest('[role="dialog"]'),
)
ok(focusInDialog, 'opening a dialog moves focus into it')

await page.keyboard.press('Escape')
await page.locator('[role="dialog"]').waitFor({ state: 'detached', timeout: 5000 })
ok(true, 'Escape closes the evidence record')

// --- Escape closes the file-a-dispute dialog too --------------------------
await page.goto(`${BASE}/app/disputes`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'File a dispute' }).click()
await page.locator('[role="dialog"]').waitFor({ timeout: 10000 })
await page.keyboard.press('Escape')
await page.locator('[role="dialog"]').waitFor({ state: 'detached', timeout: 5000 })
ok(true, 'Escape closes the file-a-dispute dialog')

// --- the packet textarea is reachable and typable -------------------------
const contest = rows.find((r) => r.recommendation === 'CONTEST')
if (contest) {
  await page.goto(`${BASE}/app/disputes/${contest.dispute_id}`, { waitUntil: 'networkidle' })
  await page.getByRole('tab', { name: /Representment/ }).click()
  const box = page.locator('textarea')
  await box.waitFor({ timeout: 10000 })
  await box.focus()
  const focused = await page.evaluate(() => document.activeElement?.tagName)
  ok(focused === 'TEXTAREA', 'the representment textarea takes keyboard focus')
}

// --- responsive boundaries ------------------------------------------------
for (const width of [1440, 1280, 1024, 900]) {
  const p2 = await newPage({ viewport: { width, height: 900 } })
  await p2.goto(`${BASE}/app/disputes`, { waitUntil: 'networkidle' })
  await p2.locator('table tbody tr').first().waitFor({ timeout: 30000 })

  const navCount = await p2.locator('a[href="/app"]:visible, a[href="/app/disputes"]:visible, a[href="/app/metrics"]:visible').count()
  const overflows = await p2.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  )
  ok(navCount >= 3, `${width}px: all three destinations are visible (${navCount})`)
  ok(!overflows, `${width}px: no horizontal page overflow`)
  await p2.screenshot({ path: `${SHOTS}/a4-w${width}.png` })
  await p2.close()
}

// --- light theme still works ---------------------------------------------
const light = await newPage({ viewport: { width: 1280, height: 900 } })
await light.addInitScript(() => localStorage.setItem('recourse.theme', 'light'))
await light.goto(`${BASE}/app/disputes`, { waitUntil: 'networkidle' })
await light.locator('table tbody tr').first().waitFor({ timeout: 30000 })
const lightBg = await light.evaluate(() => getComputedStyle(document.body).backgroundColor)
ok(lightBg === 'rgb(251, 251, 251)', `an explicit light choice still works (${lightBg})`)
const lightBlur = await light.evaluate(
  () => getComputedStyle(document.querySelector('.surface')).backdropFilter,
)
ok(lightBlur.includes('blur(0px)'), `light surfaces stay opaque, no wasted blur (${lightBlur})`)
await light.screenshot({ path: `${SHOTS}/a4-light.png` })
await light.close()

ok(errors.length === 0, `no console errors${errors.length ? ': ' + errors.join(' | ') : ''}`)
await browser.close()
