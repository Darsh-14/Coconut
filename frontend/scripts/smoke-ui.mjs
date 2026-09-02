// Optional UI smoke test: drives the real app through
//   overview -> disputes -> case -> decide -> approve -> evaluation
// and screenshots each step, in both themes.
//
// NOT part of `npm install` or the test suite: it needs Playwright plus a ~115MB browser
// download, which would work against the repo's "clone and run in five minutes" goal.
// To use it, with the backend and Vite dev server both running:
//
//   npm install && npx playwright install chromium
//   npm run verify:smoke
//
import { chromium } from 'playwright'

const SHOTS = process.env.SHOTS_DIR ?? './.smoke-shots'
const BASE = 'http://localhost:5173'

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
const page = await newPage({ viewport: { width: 1440, height: 1000 } })

const errors = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(m.text())
})
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))

const log = (...a) => console.log(...a)

// --- 1. overview ---------------------------------------------------------
await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
await page.getByText('at stake across').waitFor({ timeout: 30000 })
log(`1. OVERVIEW   heading=${JSON.stringify(await page.locator('h1').first().innerText())}`)
await page.screenshot({ path: `${SHOTS}/1-overview.png` })

// --- 2. queue ------------------------------------------------------------
await page.goto(`${BASE}/app/disputes`, { waitUntil: 'networkidle' })
await page.waitForSelector('table tbody tr', { timeout: 30000 })
const rowCount = await page.locator('table tbody tr').count()
log(`2. DISPUTES   rows=${rowCount}`)
await page.screenshot({ path: `${SHOTS}/2-disputes.png` })

// Prefer a decided, unactioned CONTEST so the approve flow is exercised. A completely
// fresh seed has no decisions, so assess deterministic queue candidates until the model
// produces one. Falling back to the first row is not enough: that row can legitimately
// abstain, which would let the approval half of this smoke test disappear.
const summaries = await (await page.request.get(`${BASE}/api/disputes`)).json()
let target = summaries.find(
  (r) => r.recommendation === 'CONTEST' && !['approved', 'submitted'].includes(r.status),
)
target ??= summaries.find((r) => r.recommendation === 'CONTEST')

if (!target) {
  for (const candidate of summaries.filter((r) => !r.recommendation)) {
    const response = await page.request.post(
      `${BASE}/api/disputes/${candidate.dispute_id}/decide`,
      { timeout: 300_000 },
    )
    if (!response.ok()) {
      throw new Error(`assessment failed for ${candidate.dispute_id}: HTTP ${response.status()}`)
    }
    const decision = await response.json()
    if (decision.recommendation === 'CONTEST') {
      target = candidate
      break
    }
  }
}
if (!target) throw new Error('the seeded queue produced no CONTEST case to exercise approval')
const targetId = target.dispute_id

// --- 3. case -------------------------------------------------------------
await page.goto(`${BASE}/app/disputes/${targetId}`, { waitUntil: 'networkidle' })
await page.getByText(/Bank.s claim/).waitFor({ timeout: 30000 })

const runBtn = page.getByRole('button', { name: /Run assessment/i })
if (await runBtn.count()) {
  log('   no standing decision; running assessment (first run loads the model)…')
  await runBtn.click()
  await page.waitForSelector('section[aria-label="Recommendation"]', { timeout: 300000 })
}

const rec = await page.locator('section[aria-label="Recommendation"] h2').innerText()
const evidenceCards = await page.locator('ol > li').count()
const marks = await page.locator('mark.span').count()
log(`3. CASE       ${targetId} rec=${JSON.stringify(rec)} evidence=${evidenceCards} spans=${marks}`)
await page.screenshot({ path: `${SHOTS}/3-case.png`, fullPage: true })

// --- 3b. evidence records ------------------------------------------------
// Every source_ref must open the record behind it, and that record must reproduce the
// evidence verbatim -- the hash is what makes "verbatim" checkable rather than asserted.
const refChips = page.locator('button[title="Open the record behind this evidence"]')
const refCount = await refChips.count()
let recordsOk = 0
for (let i = 0; i < refCount; i++) {
  await refChips.nth(i).click()
  const dialog = page.locator('[role="dialog"]')
  await dialog.waitFor({ timeout: 15000 })
  await page.waitForFunction(
    () => !document.querySelector('[role="dialog"] .skeleton'),
    undefined,
    { timeout: 15000 },
  )
  const doc = await page.evaluate(
    async ([id, idx]) => (await fetch(`/api/disputes/${id}/evidence/${idx}/document`)).json(),
    [targetId, i],
  )
  const shown = await dialog.innerText()
  const digest = [...new Uint8Array(
    await crypto.subtle.digest('SHA-256', new TextEncoder().encode(doc.body)),
  )]
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
  if (shown.includes(doc.body) && doc.content_hash === digest) recordsOk++
  if (i === 0) await page.screenshot({ path: `${SHOTS}/3b-record.png` })
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'detached', timeout: 5000 })
}
log(`3b. RECORDS   ${recordsOk}/${refCount} source_refs open and hash-verify`)
if (recordsOk !== refCount) errors.push(`only ${recordsOk}/${refCount} evidence records verified`)

// --- 4. approve, then the audit tab --------------------------------------
const approve = page.getByRole('button', { name: /^Approve/ }).first()
const alreadyActioned = await page.getByText('Human action recorded').count()
if (!alreadyActioned) {
  if (!(await approve.count())) {
    throw new Error(`${targetId} is CONTEST but has no approval control`)
  }
  const textarea = page.locator('textarea')
  if (await textarea.count()) {
    // Exercise the human-edit path: the edited text is what must be logged.
    await page.getByRole('tab', { name: /Representment/ }).click()
    await textarea.fill((await textarea.inputValue()) + '\n\nEdited during smoke test.')
  }
  await approve.click()
  // .first(): a case may already carry approvals and withdrawals from earlier runs, so
  // this must assert an entry appeared, not that exactly one exists.
  await page
    .getByText(/Approved by human|Rejected by human|Approval withdrawn/)
    .first()
    .waitFor({ timeout: 60000 })
}

// Once an approval is recorded, the action card must not offer a second approval or a
// rejection alongside the withdrawal control. That contradictory state was visible in
// the landing page's own case screenshot.
await page.getByText('Human action recorded').waitFor({ timeout: 60000 })
const conflictingActions = await page.getByRole('button', { name: /^(Approve|Reject)/ }).count()
if (conflictingActions) errors.push(`${conflictingActions} approve/reject controls remain after approval`)

await page.getByRole('tab', { name: /Audit/ }).click()
await page.getByText('Threshold', { exact: true }).first().waitFor({ timeout: 10000 })

const showPayload = page.getByRole('button', { name: /Show payload/i }).first()
if (await showPayload.count()) await showPayload.click()
const wouldSubmit = await page.getByText('Would submit to Razorpay').count()
log(`4. AUDIT      entries=${await page.locator('ol > li').count()} wouldSubmitLabel=${wouldSubmit}`)
await page.screenshot({ path: `${SHOTS}/4-audit.png`, fullPage: true })

// --- 5. evaluation -------------------------------------------------------
await page.goto(`${BASE}/app/metrics`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: /Run evaluation/i }).click()
await page.getByText('Live run, just now').waitFor({ timeout: 600000 })
log('5. EVALUATION live results rendered')
await page.screenshot({ path: `${SHOTS}/5-metrics.png`, fullPage: true })

// --- 6. dark theme -------------------------------------------------------
await page.evaluate(() => localStorage.setItem('recourse.theme', 'dark'))
await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
await page.getByText('at stake across').waitFor({ timeout: 30000 })
await page.screenshot({ path: `${SHOTS}/6-overview-dark.png` })
log('6. DARK       rendered')

log(`\nconsole errors: ${errors.length ? JSON.stringify(errors, null, 2) : 'none'}`)
await browser.close()
process.exit(errors.length ? 1 : 0)
