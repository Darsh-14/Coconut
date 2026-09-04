// Regenerates the product screenshots the landing page ships (public/shots/*.png).
//
// They are photographs of the running application rather than mockups, which is the whole
// reason they are worth having — and also the reason they rot. Change the queue's columns
// or the metrics layout and the landing page quietly advertises an older product. Re-run
// this after any visible change to the dashboard.
//
// Both themes are captured because the page shows whichever matches the visitor's; a
// half-regenerated pair means one theme silently shows the old UI.
//
//   npm install && npx playwright install chromium
//   node scripts/capture-shots.mjs          (backend + Vite dev server both running)
//
// scripts/landing-ui.mjs asserts all three load. Nothing asserts they are CURRENT — that
// judgement is yours.
import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const SESSION = JSON.stringify({ merchant: 'Kettle & Grain', at: new Date().toISOString() })
const SEEDED_TOTAL = 182
const SHOWCASE_COUNT = 15
// This is deliberately a cap-breach case: the landing section beside this photograph is
// explaining a deterministic NPCI auto-rejection, not an ordinary evidence decision.
const CASE_ID = 'disp_synthetic_0013'

// Framed to the content column, skipping the sidebar: the landing page is showing what the
// product does, and a screenshot of navigation chrome is not that.
const CLIP = { x: 250, y: 46, width: 990, height: 610 }

const PAGES = [
  ['queue', '/app/disputes'],
  ['case', `/app/disputes/${CASE_ID}`],
  ['metrics', '/app/metrics'],
]

const browser = await chromium.launch()

// A product photograph taken from a developer's mutated database is a false claim. Refuse
// to overwrite the assets unless the backend is at the clean seeded count, the showcased
// cases have no human-action history, and the featured case's NPCI forecast actually
// matches the adjacent landing copy. Computing the first fifteen decisions is the only
// intentional mutation: it gives the queue a truthful mix of outcomes instead of a staged
// empty state, and remains deterministic when the script is re-run against the same seed.
const prep = await browser.newContext()
const queue = await prep.request.get(`${BASE}/api/disputes?limit=${SHOWCASE_COUNT}`)
if (!queue.ok()) throw new Error(`queue preflight failed: HTTP ${queue.status()}`)
const total = Number(queue.headers()['x-total-count'])
if (total !== SEEDED_TOTAL) {
  throw new Error(
    `refusing to capture a mutated database: expected ${SEEDED_TOTAL} disputes, found ${total}`,
  )
}
const showcase = await queue.json()
if (showcase.length !== SHOWCASE_COUNT) {
  throw new Error(`expected ${SHOWCASE_COUNT} showcase disputes, found ${showcase.length}`)
}

for (const summary of showcase) {
  const response = await prep.request.get(`${BASE}/api/disputes/${summary.dispute_id}`)
  if (!response.ok()) {
    throw new Error(`${summary.dispute_id} preflight failed: HTTP ${response.status()}`)
  }
  const item = await response.json()
  if (item.audit_log.length) {
    throw new Error(`refusing to capture ${summary.dispute_id}: it has human-action history`)
  }
  if (!item.latest_decision) {
    const decided = await prep.request.post(
      `${BASE}/api/disputes/${summary.dispute_id}/decide`,
      {
        // The first call loads the 715MB model. A cold CPU start is expected to take longer
        // than Playwright's request default; subsequent calls are fast.
        timeout: 180_000,
      },
    )
    if (!decided.ok()) {
      throw new Error(`${summary.dispute_id} decision failed: HTTP ${decided.status()}`)
    }
  }
}

const before = await prep.request.get(`${BASE}/api/disputes/${CASE_ID}`)
if (!before.ok()) throw new Error(`case preflight failed: HTTP ${before.status()}`)
let detail = await before.json()
if (detail.audit_log.length) {
  throw new Error(`refusing to capture ${CASE_ID}: it already has human-action history`)
}

const forecast = await prep.request.get(`${BASE}/api/disputes/${CASE_ID}/urcs-forecast`)
if (!forecast.ok() || (await forecast.json()).predicted_disposition !== 'AUTO_REJECT') {
  throw new Error(`${CASE_ID} is no longer an NPCI auto-reject; choose a truthful case`)
}

if (!detail.latest_decision) {
  const decided = await prep.request.post(`${BASE}/api/disputes/${CASE_ID}/decide`, {
    timeout: 180_000,
  })
  if (!decided.ok()) throw new Error(`case decision failed: HTTP ${decided.status()}`)
  detail = await decided.json()
}
if (detail.recommendation !== 'NO_ACTION_NEEDED' && detail.latest_decision?.recommendation !== 'NO_ACTION_NEEDED') {
  throw new Error(`${CASE_ID} did not produce NO_ACTION_NEEDED`)
}
await prep.close()

for (const theme of ['dark', 'light']) {
  const context = await browser.newContext({
    viewport: { width: 1240, height: 900 },
    // Retina-ish, so the downscaled image on the landing page stays crisp.
    deviceScaleFactor: 1.5,
  })
  await context.addInitScript(
    ([session, chosen]) => {
      localStorage.setItem('coconut.session', session)
      localStorage.setItem('coconut.theme', chosen)
    },
    [SESSION, theme],
  )

  const page = await context.newPage()
  for (const [name, path] of PAGES) {
    await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
    // The queue paints rows only after the fetch resolves; the other two settle on their
    // own. Waiting on the row is what stops an empty table being captured.
    if (name === 'queue') await page.locator('table tbody tr').first().waitFor({ timeout: 30000 })
    if (name === 'case') {
      await page.getByText('NPCI dispute budget', { exact: true }).waitFor({ timeout: 30000 })
      await page.getByText('NPCI will reject this for you', { exact: true }).waitFor({ timeout: 30000 })
    }
    if (name === 'metrics') {
      await page.getByText('Risk budget', { exact: true }).waitFor({ timeout: 30000 })
    }
    await page.waitForTimeout(1200)
    await page.screenshot({ path: `public/shots/${name}-${theme}.png`, clip: CLIP })
    console.log(`  captured ${name}-${theme}.png`)
  }
  await context.close()
}

await browser.close()
console.log('\nDone. Check them before committing — a stale screenshot is a false claim.')
