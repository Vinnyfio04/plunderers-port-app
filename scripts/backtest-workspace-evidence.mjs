// Read-only screenshots of an actual saved run in the running workstation.
// Starts/stops only its own headless Chrome; no backtests, orders or model calls.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { promises as fs, existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const base = process.env.BACKTEST_WORKSPACE_URL || 'http://127.0.0.1:5173'
const runId = process.env.BACKTEST_RUN_ID
const layoutOnly = process.argv.includes('--layout-only')
const evidence = path.join(root, 'docs', 'evidence', `${layoutOnly ? 'workspace-layout' : 'backtest-workspace'}-${Date.now()}`)
const profile = path.join(root, 'backend', 'data', `evidence-chrome-${Date.now()}`)
const chromePath = process.env.SMOKE_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
let browser, page, child
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms))
async function wait(check, label) {
  const start = Date.now()
  while (Date.now() - start < 30000) { const answer = await check(); if (answer) return answer; await sleep(200) }
  throw new Error(`Timed out: ${label}`)
}
async function connect(url) {
  const socket = new WebSocket(url), pending = new Map()
  let sequence = 0
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }) })
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(String(data)), callback = pending.get(message.id)
    if (!callback) return
    pending.delete(message.id); clearTimeout(callback.timer)
    message.error ? callback.reject(new Error(message.error.message)) : callback.resolve(message.result)
  })
  return {
    close: () => socket.close(),
    send: (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence, timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)) }, 15000)
      pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params }))
    }),
  }
}
async function evaluate(expression) {
  const response = await page.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text)
  return response.result.value
}
async function shot(name) {
  const capture = await page.send('Page.captureScreenshot', { format: 'png' })
  await fs.writeFile(path.join(evidence, name), Buffer.from(capture.data, 'base64'))
}
try {
  assert.ok(existsSync(chromePath), 'Use installed Chrome or SMOKE_CHROME')
  let selected, expected
  if (!layoutOnly) {
  const response = await fetch(`${base}/api/backtests?limit=100&offset=0`)
  assert.ok(response.ok, 'Running workstation backtest API is available')
  const saved = (await response.json()).runs
  selected = runId ? saved.find(row => row.run_id === runId) : saved.find(row => row.settings.symbol === 'AAPL')
  assert.ok(selected, 'An actual cached AAPL backtest from step 4 is saved; this script never creates one')
  expected = await fetch(`${base}/api/backtests/${selected.run_id}`).then(r => r.json())
  }
  child = spawn(chromePath, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--window-size=1440,1100', 'about:blank'], { windowsHide: true, stdio: 'ignore' })
  const content = await wait(() => existsSync(path.join(profile, 'DevToolsActivePort')) ? fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8') : false, 'Chrome')
  const [port, endpoint] = content.trim().split(/\r?\n/)
  browser = await connect(`ws://127.0.0.1:${port}${endpoint}`)
  const target = await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(base)}`, { method: 'PUT' }).then(r => r.json())
  page = await connect(target.webSocketDebuggerUrl)
  await page.send('Runtime.enable')
  await wait(() => evaluate(`Boolean(document.querySelector('.backtest-workspace'))`), 'Vue workspace')
  if (layoutOnly) {
    await wait(() => evaluate(`document.querySelector('[aria-label="Inspect candle by UTC timestamp"]')?.options.length>0 &&
      document.querySelector('[aria-label="Indicator type"]')?.options.length>0 && !document.querySelector('.indicator-form button').disabled`), 'loaded chart and indicator controls')
    await page.send('Emulation.setDeviceMetricsOverride', { width: 1009, height: 871, deviceScaleFactor: 1, mobile: false })
    await evaluate(`document.querySelectorAll('.workspace-sidebar > details').forEach(el=>el.open=false);
      document.querySelector('[data-testid="indicator-dock"]').open=true;
      document.querySelector('.workspace-sidebar').scrollTop=0;window.scrollTo(0,0)`)
    const structure=await evaluate(`(()=>{const main=document.querySelector('.workspace-main'),aside=document.querySelector('.workspace-sidebar');
      return {indicators_in_sidebar:Boolean(aside.querySelector('.indicator-dock .indicator-form')),chart_last:main.lastElementChild.classList.contains('chart-panel'),
        no_page_overflow:document.documentElement.scrollWidth<=window.innerWidth+1}})()`)
    assert.deepEqual(structure,{indicators_in_sidebar:true,chart_last:true,no_page_overflow:true})
    await fs.mkdir(evidence,{recursive:true})
    await shot('workspace_indicators.png')
    await fs.writeFile(path.join(evidence,'observed.json'),JSON.stringify({provenance:'Actual running workstation, read-only layout inspection; no model/order request and no fixture writes.',viewport:{width:1009,height:871},...structure},null,2))
    console.log(`PASS running-workstation layout evidence: ${evidence}`)
  } else {
  await evaluate(`document.querySelector('.backtest-workspace').open=true`)
  await wait(() => evaluate(`Boolean(document.querySelector('[data-run-id="${selected.run_id}"]'))`), 'Saved run control')
  await evaluate(`document.querySelector('[data-run-id="${selected.run_id}"]').click()`)
  await wait(() => evaluate(`document.querySelector('[data-testid="backtest-run-id"]')?.textContent===${JSON.stringify(selected.run_id)}`), 'Saved result')
  await wait(() => evaluate(`Boolean(document.querySelector('[data-testid="backtest-provenance"]'))`), 'Saved provenance')
  const metrics = await evaluate(`Object.fromEntries(['equity','cash','pnl','realized','unrealized','shares','return'].map(key=>[key,document.querySelector('[data-testid="backtest-'+key+'"]').textContent]))`)
  assert.equal(metrics.equity, `$${expected.summary.equity.toFixed(2)}`)
  assert.equal(metrics.shares, String(expected.summary.shares))
  const fills = await evaluate(`document.querySelector('[data-testid="backtest-orders-table"]')?.textContent`)
  for (const order of expected.orders.slice(0, 25)) {
    assert.ok(fills.includes(`${order.order_id} · ${order.action} · ${order.status}`))
    if (order.fill) assert.ok(fills.includes(`$${order.fill.price.toFixed(2)}`))
  }
  const decisionPage = await evaluate(`document.querySelector('[aria-label="Next Decisions"]').click();true`)
  assert.ok(decisionPage)
  await wait(() => evaluate(`document.querySelector('[data-testid="backtest-decisions-table"] tbody tr td')?.textContent===${JSON.stringify(expected.decisions[25].bar_time.replace('T',' ').replace('Z',' UTC'))}`), 'Second page of chronological decisions')
  await evaluate(`document.querySelector('[aria-label="Next Equity audit"]').click()`)
  await wait(() => evaluate(`document.querySelector('[data-testid="backtest-equity-table"] tbody tr td')?.textContent.includes(${JSON.stringify(expected.equity[25].event_id)})`), 'Second page of equity events')
  await fs.mkdir(evidence, { recursive: true })
  await evaluate(`document.querySelector('.backtest-result').scrollIntoView({block:'start'});window.scrollBy(0,-110)`)
  await shot('saved_aapl_performance.png')
  await evaluate(`document.querySelector('[aria-label="Orders and fills"]').scrollIntoView({block:'start'});window.scrollBy(0,-110)`)
  await shot('saved_aapl_fills.png')
  await page.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
  await evaluate(`document.querySelector('.backtest-result').scrollIntoView({block:'start'})`)
  assert.ok(await evaluate(`document.documentElement.scrollWidth<=window.innerWidth+1`), 'Mobile result fits the page')
  await shot('saved_aapl_mobile.png')
  await fs.writeFile(path.join(evidence, 'observed.json'), JSON.stringify({ provenance: 'Previously cached Yahoo-origin AAPL history; read-only saved-run inspection, not a fresh Yahoo observation or a live trade.',
    run_id: expected.run_id, settings: expected.settings, summary: expected.summary, metrics, result_hash: expected.result_hash, dataset_hash: expected.dataset_hash,
    checks: ['UI metrics agree with saved API result', 'Displayed order IDs/statuses/fill prices agree with saved result', 'Decision and equity audit second pages agree with saved event timestamps/IDs', 'Source provenance loaded', '390px mobile has no page overflow'] }, null, 2))
  console.log(`PASS saved-workstation evidence: ${evidence}`)
  }
} finally {
  if (page) page.close()
  if (browser) { await browser.send('Browser.close').catch(() => {}); browser.close() }
  if (child && child.exitCode === null) {
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(5000)])
    if (child.exitCode === null) child.kill()
  }
  // Only this script's verified temporary profile, never a user's existing browser profile.
  const allowed = path.join(root, 'backend', 'data') + path.sep
  assert.ok(profile.startsWith(allowed) && path.basename(profile).startsWith('evidence-chrome-'))
  await fs.rm(profile, { recursive: true, force: true, maxRetries: 8, retryDelay: 250 })
}
