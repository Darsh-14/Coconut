// Capture a reproducible README gallery from the isolated demo workspace.
//
// Run app.demo:app on port 8011 first. This script resets that disposable database,
// executes the four real decision paths, records one human approval, and photographs
// both the product UI and backend state. It never touches the normal application DB.
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8011'
const OUTPUT = fileURLToPath(new URL('../public/shots/', import.meta.url))
const SESSION = JSON.stringify({ merchant: 'Kettle & Grain', at: new Date().toISOString() })
const VIEWPORT = { width: 1440, height: 960 }
const CONTENT = { x: 220, y: 0, width: 1220, height: 920 }

await mkdir(OUTPUT, { recursive: true })

const browser = await chromium.launch()
try {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1.5,
    colorScheme: 'light',
  })
  await context.addInitScript(session => {
    localStorage.setItem('coconut.session', session)
    localStorage.setItem('coconut.theme', 'light')
  }, SESSION)

  const request = context.request
  const workspace = await json(request.get(`${BASE}/api/workspace`), 'workspace check')
  if (workspace.demo !== true) {
    throw new Error('Refusing to capture: app.demo:app is not running at BASE_URL')
  }

  await ok(request.post(`${BASE}/api/demo/reset`), 'demo reset')
  const { scenarios } = await json(
    request.get(`${BASE}/api/demo/scenarios`),
    'scenario list',
  )
  const byLabel = Object.fromEntries(scenarios.map(item => [item.label, item]))
  for (const label of ['Contest', 'Accept', 'Human review', 'UPI limit']) {
    if (!byLabel[label]) throw new Error(`Demo scenario missing: ${label}`)
    await ok(
      request.post(`${BASE}/api/disputes/${byLabel[label].id}/decide`, {
        timeout: 240_000,
      }),
      `${label} assessment`,
    )
  }

  const page = await context.newPage()

  await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Home', exact: true }).waitFor()
  await settle(page)
  await capture(page, 'readme-overview.png', CONTENT)

  const contestId = byLabel.Contest.id
  await page.goto(`${BASE}/app/disputes/${contestId}`, { waitUntil: 'networkidle' })
  await page.getByText('Recommendation', { exact: true }).waitFor()
  await page.getByRole('tab', { name: /Evidence/ }).click()
  await settle(page)
  await capture(page, 'readme-evidence.png', CONTENT)

  const upiId = byLabel['UPI limit'].id
  await page.goto(`${BASE}/app/disputes/${upiId}`, { waitUntil: 'networkidle' })
  await page.getByText('NPCI dispute budget', { exact: true }).waitFor()
  await page.getByText('NPCI will reject this for you', { exact: true }).waitFor()
  await settle(page)
  await capture(page, 'readme-upi.png', CONTENT)

  const openapi = await json(request.get(`${BASE}/api/openapi.json`), 'OpenAPI schema')
  await renderApiSurface(page, openapi)
  await capture(page, 'readme-api.png', { x: 0, y: 0, ...VIEWPORT })

  // Record a real demo approval so the backend photograph can show persisted state and
  // the exact simulated payload. Fetching these values again after approval proves the
  // image is built from the server response rather than from hard-coded copy.
  let detail = await json(
    request.get(`${BASE}/api/disputes/${contestId}`),
    'contest detail',
  )
  await ok(
    request.post(`${BASE}/api/disputes/${contestId}/approve`, {
      data: {
        decision_id: detail.latest_decision_id,
        approved: true,
        edited_packet: detail.latest_decision.drafted_packet,
      },
    }),
    'human approval',
  )
  detail = await json(
    request.get(`${BASE}/api/disputes/${contestId}`),
    'approved contest detail',
  )
  const health = await json(request.get(`${BASE}/api/health`), 'health check')
  const exported = await json(
    request.get(`${BASE}/api/disputes/${contestId}/would-submit.json`),
    'simulated payload export',
  )
  const latestAudit = detail.audit_log.at(-1)
  const backendState = {
    live_endpoints: [
      'GET /api/health',
      `GET /api/disputes/${contestId}`,
      `GET /api/disputes/${contestId}/would-submit.json`,
    ],
    health: {
      status: health.status,
      database: health.database,
      model_loaded: health.model_loaded,
      calibrated: health.calibrated,
    },
    safety_boundary: {
      razorpay_mode: health.razorpay_mode,
      auto_submit_enabled: health.auto_submit_to_razorpay,
      transmitted: exported.transmitted,
      payload_note: exported.would_be_razorpay_payload._coconut_note,
    },
    persisted_decision: {
      dispute_id: contestId,
      recommendation: detail.latest_decision.recommendation,
      confidence: detail.latest_decision.confidence,
      model_version: detail.latest_decision.model_version,
      calibrated_threshold_used: detail.latest_decision.calibrated_threshold_used,
      evidence_verdicts: detail.latest_decision.claim_verdicts.map(verdict => ({
        evidence_index: verdict.evidence_index,
        label: verdict.label,
        confidence: verdict.confidence,
      })),
    },
    audit_record: {
      approved_by_human: latestAudit.approved_by_human,
      withdrawn: latestAudit.withdrawn,
      payload_prepared: Boolean(latestAudit.would_be_razorpay_payload),
    },
    prepared_payload: {
      action: exported.would_be_razorpay_payload.action,
      amount: exported.would_be_razorpay_payload.amount,
      evidence_sources: exported.would_be_razorpay_payload.shipping_proof,
    },
  }
  await renderBackendState(page, backendState)
  await capture(page, 'readme-backend-state.png', { x: 0, y: 0, ...VIEWPORT })

  await context.close()
} finally {
  await browser.close()
}

console.log('Captured README gallery from the isolated demo workspace.')

async function ok(promise, label) {
  const response = await promise
  if (!response.ok()) {
    throw new Error(`${label} failed: HTTP ${response.status()} ${await response.text()}`)
  }
  return response
}

async function json(promise, label) {
  return (await ok(promise, label)).json()
}

async function settle(page) {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(800)
}

async function capture(page, name, clip) {
  await page.screenshot({
    path: `${OUTPUT}${name}`,
    clip,
    animations: 'disabled',
  })
  console.log(`  captured ${name}`)
}

async function renderBackendState(page, state) {
  const formatted = value => escapeHtml(JSON.stringify(value, null, 2))
  await page.setContent(`<!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>Coconut backend state</title>
        <style>
          :root { color-scheme: dark; }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            min-height: 100vh;
            background: #0d1117;
            color: #e6edf3;
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
          }
          header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 24px 32px;
            border-bottom: 1px solid #30363d;
            background: #161b22;
          }
          h1 { margin: 0; font: 600 19px Inter, system-ui, sans-serif; }
          .live { color: #3fb950; font: 600 13px Inter, system-ui, sans-serif; }
          main { padding: 24px 32px 32px; }
          .label {
            margin-bottom: 13px;
            color: #8b949e;
            font: 600 12px Inter, system-ui, sans-serif;
            letter-spacing: .08em;
            text-transform: uppercase;
          }
          .grid { display: grid; grid-template-columns: .86fr 1.14fr; gap: 16px; align-items: start; }
          .column { display: grid; gap: 16px; }
          .card { padding: 16px 18px; border: 1px solid #30363d; border-radius: 10px; background: #11161d; }
          h2 { margin: 0 0 10px; color: #9da7b3; font: 650 12px Inter, system-ui, sans-serif; letter-spacing: .07em; text-transform: uppercase; }
          pre {
            margin: 0;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            font-size: 12.5px;
            line-height: 1.42;
          }
        </style>
      </head>
      <body>
        <header>
          <h1>Coconut · persisted decision and audit state</h1>
          <span class="live">● LIVE DEMO API</span>
        </header>
        <main>
          <div class="label">Responses fetched after a human-approved contest</div>
          <div class="grid">
            <div class="column">
              <section class="card"><h2>Live endpoints</h2><pre>${formatted(state.live_endpoints)}</pre></section>
              <section class="card"><h2>Health</h2><pre>${formatted(state.health)}</pre></section>
              <section class="card"><h2>Safety boundary</h2><pre>${formatted(state.safety_boundary)}</pre></section>
            </div>
            <div class="column">
              <section class="card"><h2>Persisted decision</h2><pre>${formatted(state.persisted_decision)}</pre></section>
              <section class="card"><h2>Human audit record</h2><pre>${formatted(state.audit_record)}</pre></section>
              <section class="card"><h2>Prepared payload</h2><pre>${formatted(state.prepared_payload)}</pre></section>
            </div>
          </div>
        </main>
      </body>
    </html>`)
  await page.evaluate(() => document.fonts.ready)
}

async function renderApiSurface(page, schema) {
  const preferred = [
    '/health',
    '/ready',
    '/disputes',
    '/disputes/{dispute_id}',
    '/disputes/{dispute_id}/decide',
    '/disputes/{dispute_id}/approve',
    '/disputes/{dispute_id}/evidence',
    '/disputes/{dispute_id}/would-submit.json',
    '/calibrate',
    '/verify-guarantee',
    '/evaluate',
    '/webhooks/razorpay',
  ]
  const routes = preferred.flatMap(path =>
    Object.entries(schema.paths[path] ?? {}).map(([method, operation]) => ({
      method: method.toUpperCase(),
      path,
      summary: operation.summary ?? '',
    })),
  )
  const rows = routes.map(route => `
    <li>
      <span class="method ${route.method.toLowerCase()}">${escapeHtml(route.method)}</span>
      <code>${escapeHtml(route.path)}</code>
      <span class="summary">${escapeHtml(route.summary)}</span>
    </li>`).join('')
  await page.setContent(`<!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>Coconut API surface</title>
        <style>
          * { box-sizing: border-box; }
          body { margin: 0; background: #f7f8fa; color: #111827; font-family: Inter, system-ui, sans-serif; }
          header { padding: 28px 36px 24px; color: white; background: #101827; }
          .top { display: flex; align-items: center; justify-content: space-between; }
          h1 { margin: 0; font-size: 25px; letter-spacing: -.02em; }
          .live { color: #5ee28a; font-size: 13px; font-weight: 700; }
          header p { margin: 9px 0 0; color: #aeb8c8; font-size: 14px; }
          main { padding: 24px 36px 32px; }
          .source { margin-bottom: 13px; color: #64748b; font: 600 12px ui-monospace, monospace; }
          ul { margin: 0; padding: 0; overflow: hidden; border: 1px solid #dce1e8; border-radius: 12px; background: white; list-style: none; }
          li { display: grid; grid-template-columns: 74px minmax(350px, 1fr) 1.2fr; align-items: center; gap: 14px; min-height: 57px; padding: 10px 16px; border-bottom: 1px solid #e8ebef; }
          li:last-child { border-bottom: 0; }
          code { color: #162033; font-size: 13px; font-weight: 650; }
          .summary { color: #64748b; font-size: 13px; }
          .method { display: inline-flex; justify-content: center; border-radius: 6px; padding: 5px 7px; color: white; font: 750 11px ui-monospace, monospace; }
          .get { background: #1677c8; } .post { background: #21834b; }
          .put { background: #a55b09; } .delete { background: #c13636; }
        </style>
      </head>
      <body>
        <header>
          <div class="top">
            <h1>${escapeHtml(schema.info.title)} · FastAPI surface</h1>
            <span class="live">● LIVE OPENAPI SCHEMA</span>
          </div>
          <p>Version ${escapeHtml(schema.info.version)} · typed routes for decisions, evidence, risk control and audit</p>
        </header>
        <main>
          <div class="source">GET /api/openapi.json · ${routes.length} selected operations</div>
          <ul>${rows}</ul>
        </main>
      </body>
    </html>`)
  await page.evaluate(() => document.fonts.ready)
}

function escapeHtml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}
