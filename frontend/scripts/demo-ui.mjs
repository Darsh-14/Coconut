// Run only against app.demo:app; this test resets its disposable database.
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:8011'
const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  assert.equal((await (await page.request.get(`${base}/api/workspace`)).json()).demo, true)
  assert.equal((await page.request.post(`${base}/api/demo/reset`)).status(), 200)
  await page.goto(`${base}/login`)
  await page.getByRole('button', { name: 'Try demo', exact: true }).click()
  await page.getByRole('region', { name: 'Demo workspace' }).waitFor()
  const scenarios = (await (await page.request.get(`${base}/api/demo/scenarios`)).json()).scenarios
  const expected = ['CONTEST', 'ACCEPT', 'NEEDS_HUMAN_REVIEW', 'NO_ACTION_NEEDED']
  for (const [index, scenario] of scenarios.entries()) {
    const response = await page.request.post(`${base}/api/disputes/${scenario.id}/decide`, { timeout: 240000 })
    assert.equal(response.status(), 200, await response.text())
    const decision = await response.json()
    assert.equal(decision.recommendation, expected[index])
    console.log(`PASS real assessment: ${scenario.label} -> ${decision.recommendation}`)
  }
  await page.getByRole('region', { name: 'Demo workspace' }).getByRole('link', { name: 'Contest', exact: true }).click()
  await page.getByRole('tab', { name: /Representment/ }).click()
  const packet = page.getByRole('textbox', { name: 'Representment packet' })
  await packet.fill((await packet.inputValue()) + '\nDemo reviewer edit.')
  await page.getByRole('button', { name: /^Approve/ }).first().click()
  await page.getByText('Human action recorded', { exact: true }).waitFor()
  await page.getByRole('tab', { name: /Representment/ }).click()
  assert.equal(await packet.isDisabled(), true)
  const detail = await (await page.request.get(`${base}/api/disputes/${scenarios[0].id}`)).json()
  assert.equal(['approved', 'submitted'].includes(detail.status), true)
  await page.getByRole('button', { name: 'Reset demo', exact: true }).click()
  await page.getByRole('button', { name: 'Confirm reset', exact: true }).click()
  await page.waitForURL(`${base}/app`)
  const resetRows = await (await page.request.get(`${base}/api/disputes`)).json()
  assert.equal(resetRows.every(row => row.recommendation === null), true)
  console.log('PASS edit, approval, and reset through the UI')
  for (const width of [320, 375, 900, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
  }
  console.log('PASS responsive demo strip')
} finally {
  await browser.close()
}
