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
//   npm i -D playwright && npx playwright install chromium
//   node scripts/capture-shots.mjs          (backend + Vite dev server both running)
//
// scripts/landing-ui.mjs asserts all three load. Nothing asserts they are CURRENT — that
// judgement is yours.
import { chromium } from 'playwright'

const BASE = 'http://localhost:5173'
const SESSION = JSON.stringify({ merchant: 'Kettle & Grain', at: new Date().toISOString() })

// Framed to the content column, skipping the sidebar: the landing page is showing what the
// product does, and a screenshot of navigation chrome is not that.
const CLIP = { x: 250, y: 46, width: 990, height: 610 }

const PAGES = [
  ['queue', '/app/disputes'],
  ['case', '/app/disputes/disp_synthetic_0004'],
  ['metrics', '/app/metrics'],
]

const browser = await chromium.launch()

for (const theme of ['dark', 'light']) {
  const context = await browser.newContext({
    viewport: { width: 1240, height: 900 },
    // Retina-ish, so the downscaled image on the landing page stays crisp.
    deviceScaleFactor: 1.5,
  })
  await context.addInitScript(
    ([session, chosen]) => {
      localStorage.setItem('recourse.session', session)
      localStorage.setItem('recourse.theme', chosen)
    },
    [SESSION, theme],
  )

  const page = await context.newPage()
  for (const [name, path] of PAGES) {
    await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
    // The queue paints rows only after the fetch resolves; the other two settle on their
    // own. Waiting on the row is what stops an empty table being captured.
    if (name === 'queue') await page.locator('table tbody tr').first().waitFor({ timeout: 30000 })
    await page.waitForTimeout(1200)
    await page.screenshot({ path: `public/shots/${name}-${theme}.png`, clip: CLIP })
    console.log(`  captured ${name}-${theme}.png`)
  }
  await context.close()
}

await browser.close()
console.log('\nDone. Check them before committing — a stale screenshot is a false claim.')
