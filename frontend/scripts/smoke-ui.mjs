// Optional UI smoke test: drives the real app through
//   queue -> case -> decide -> approve -> metrics
// and screenshots each step.
//
// NOT part of `npm install` or the test suite: it needs Playwright plus a ~115MB browser
// download, which would work against the repo's "clone and run in five minutes" goal.
// To use it, with the backend and Vite dev server both running:
//
//   npm i -D playwright && npx playwright install chromium
//   node scripts/smoke-ui.mjs
//
import { chromium } from 'playwright'

const SHOTS = process.env.SHOTS_DIR ?? './.smoke-shots'
const BASE = 'http://localhost:5173'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })

const errors = []
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))

function log(...a) { console.log(...a) }

// --- 1. queue ------------------------------------------------------------
await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('table tbody tr', { timeout: 30000 })
const rowCount = await page.locator('table tbody tr').count()
const heading = await page.locator('h1').first().innerText()
const urgent = await page.locator('td.text-red-700').count()
log(`1. QUEUE      heading=${JSON.stringify(heading)} rows=${rowCount} urgent(red)=${urgent}`)
await page.screenshot({ path: `${SHOTS}/1-queue.png`, fullPage: false })

// Prefer a dispute already decided CONTEST so the approve flow is exercised.
// Fall back to the first row and decide it in the UI.
let targetId = null
const res = await page.request.get(`${BASE}/api/disputes`)
const rows = await res.json()
for (const r of rows.slice(0, 40)) {
  const d = await page.request.get(`${BASE}/api/disputes/${r.dispute_id}`)
  const detail = await d.json()
  if (detail.latest_decision?.recommendation === 'CONTEST') { targetId = r.dispute_id; break }
}
if (!targetId) targetId = rows[0].dispute_id
log(`   picked ${targetId}`)

// --- 2. case detail ------------------------------------------------------
await page.goto(`${BASE}/disputes/${targetId}`, { waitUntil: 'networkidle' })
await page.waitForSelector('h1', { timeout: 20000 })

// If not yet assessed, click the button and wait for the banner.
const runBtn = page.getByRole('button', { name: /Run assessment/i })
if (await runBtn.count()) {
  log('   no decision yet -> clicking "Run assessment"')
  await runBtn.click()
  await page.waitForSelector('section[aria-label="Recommendation"]', { timeout: 180000 })
}

const rec = await page.locator('section[aria-label="Recommendation"] h2').innerText()
const evidenceCards = await page.locator('ol > li').count()
const marks = await page.locator('mark').count()
const badges = await page.locator('span:has-text("%")').count()
log(`2. CASE       recommendation=${JSON.stringify(rec)} evidenceCards=${evidenceCards} highlightedSpans=${marks}`)
await page.screenshot({ path: `${SHOTS}/2-case.png`, fullPage: true })

// --- 3. approve ----------------------------------------------------------
const approve = page.getByRole('button', { name: /Approve/i }).first()
let approved = false
if (await approve.count()) {
  const textarea = page.locator('textarea')
  const hadPacket = (await textarea.count()) > 0
  if (hadPacket) {
    const len = (await textarea.inputValue()).length
    log(`   drafted packet in textarea: ${len} chars`)
  }
  await approve.click()
  await page.waitForTimeout(2500)
  approved = true
}
const auditEntries = await page.locator('h2:has-text("Audit trail") ~ ol > li').count()
const wouldSubmit = await page.locator('text=Would submit to Razorpay').count()
log(`3. APPROVE    clicked=${approved} auditEntries=${auditEntries} wouldSubmitBanner=${wouldSubmit}`)

// Expand the payload so the screenshot shows it.
const showBtn = page.getByRole('button', { name: /Show payload/i }).first()
if (await showBtn.count()) { await showBtn.click(); await page.waitForTimeout(400) }
await page.screenshot({ path: `${SHOTS}/3-approved.png`, fullPage: true })

// --- 4. status reflected back in the queue -------------------------------
await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('table tbody tr')
const statusCell = await page.locator(`tr:has-text("${targetId.replace('disp_synthetic_', '#')}") td:last-child`).first().innerText().catch(() => '?')
log(`4. QUEUE AGAIN status of ${targetId} = ${JSON.stringify(statusCell.trim())}`)

// --- 5. metrics ----------------------------------------------------------
await page.goto(`${BASE}/metrics`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: /Run evaluation/i }).click()
await page.waitForSelector('table tbody tr', { timeout: 600000 })
const stats = await page.locator('p.font-mono.text-3xl').allInnerTexts()
const cmCells = await page.locator('table tbody tr').allInnerTexts()
log(`5. METRICS    cards=${JSON.stringify(stats)}`)
log(`   confusion: ${cmCells.map(s => s.replace(/\s+/g, ' ').trim()).join(' | ')}`)
await page.screenshot({ path: `${SHOTS}/5-metrics.png`, fullPage: true })

log(`\nconsole errors: ${errors.length}`)
errors.slice(0, 8).forEach(e => log('  ', e))

await browser.close()
