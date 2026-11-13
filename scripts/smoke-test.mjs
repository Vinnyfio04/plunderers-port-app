// One-command, dependency-free browser SmokeTest using installed Chrome and CDP.
import assert from 'node:assert/strict'
import { spawn, execFile } from 'node:child_process'
import { createServer } from 'node:http'
import { promises as fs, existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { inflateSync } from 'node:zlib'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const runsRoot = path.join(root, 'backend', 'data', 'smoke-runs')
const runDir = path.join(runsRoot, `smoke-${Date.now()}-${process.pid}`)
const database = path.join(runDir, 'market.sqlite3')
const candlesFile = path.join(runDir, 'candles.csv')
const captures = path.join(runDir, 'captures')
const chromeProfile = path.join(runDir, 'chrome-profile')
const execFileAsync = promisify(execFile)
const started = []
let chrome
let browserCdp
let pageCdp
let provider
let failed = false
let interrupted = false
process.on('SIGINT', () => { interrupted = true })
process.on('SIGTERM', () => { interrupted = true })

function checkInterrupt() { if (interrupted) throw new Error('SmokeTest interrupted') }
function log(message) { console.log(`[SmokeTest] ${message}`) }
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function freePort() {
  const server = createServer()
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  await new Promise((resolve) => server.close(resolve))
  return port
}

function findPython() {
  if (process.env.SMOKE_PYTHON) return process.env.SMOKE_PYTHON
  const local = 'C:\\Users\\Owner\\AppData\\Local\\Programs\\Python\\Python313\\python.exe'
  return process.platform === 'win32' && existsSync(local) ? local : 'python'
}

function findChrome() {
  if (process.env.SMOKE_CHROME) return process.env.SMOKE_CHROME
  const candidates = process.platform === 'win32'
    ? ['C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
       'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
       'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe']
    : ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']
  const found = candidates.find((candidate) => existsSync(candidate))
  if (!found) throw new Error('No installed Chrome/Edge browser found; set SMOKE_CHROME to its path.')
  return found
}

function start(command, args, env, name, cwd = root) {
  const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'] })
  const record = { child, name, output: '' }
  for (const stream of [child.stdout, child.stderr]) {
    stream.on('data', (chunk) => { record.output = (record.output + chunk.toString()).slice(-12000) })
  }
  child.on('error', (error) => { record.output += `\nProcess error: ${error.message}` })
  started.push(record)
  return child
}

async function runPython(args) {
  const { stdout } = await execFileAsync(findPython(), args, { cwd: root, maxBuffer: 2_000_000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } })
  return stdout.trim()
}

async function waitFor(check, label, timeout = 20000) {
  const startAt = Date.now()
  let last
  while (Date.now() - startAt < timeout) {
    checkInterrupt()
    try { last = await check(); if (last) return last } catch (error) { last = error.message }
    await sleep(200)
  }
  throw new Error(`Timed out waiting for ${label}; last=${JSON.stringify(last)}`)
}

async function ready(url, name) {
  await waitFor(async () => {
    const response = await fetch(url, { signal: AbortSignal.timeout(1000) })
    return response.ok
  }, name, 30000)
  log(`${name} ready: ${url}`)
}

function decodePixels(dataUrl) {
  assert.ok(dataUrl.startsWith('data:image/png;base64,'), 'provider received PNG data URL')
  const png = Buffer.from(dataUrl.split(',', 2)[1], 'base64')
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', 'PNG signature')
  let offset = 8
  let width = 0; let height = 0; let depth = 0; let color = 0
  const imageData = []
  while (offset + 12 <= png.length) {
    const length = png.readUInt32BE(offset)
    const type = png.toString('ascii', offset + 4, offset + 8)
    const chunk = png.subarray(offset + 8, offset + 8 + length)
    if (type === 'IHDR') {
      width = chunk.readUInt32BE(0); height = chunk.readUInt32BE(4)
      depth = chunk[8]; color = chunk[9]
    }
    if (type === 'IDAT') imageData.push(chunk)
    offset += length + 12
    if (type === 'IEND') break
  }
  assert.ok(width >= 320 && height >= 200, 'chart pixels have readable dimensions')
  assert.equal(depth, 8, 'chart PNG has 8-bit pixels')
  assert.ok(color === 6 || color === 2, `chart PNG color type ${color} is RGB/RGBA`)
  const pixels = inflateSync(Buffer.concat(imageData))
  const channels = color === 6 ? 4 : 3
  assert.equal(pixels.length, height * (1 + width * channels), 'decoded pixel rows')
  assert.ok(new Set(pixels.subarray(0, Math.min(pixels.length, 20000))).size > 8,
    'chart image has varied decoded pixel data')
  return { width, height, decodedBytes: pixels.length }
}

function startProvider() {
  const requests = []
  const state = { failNextAnalyst: false }
  const actions = {
    '14:32': ['wait', 'downward', 'accept'],
    '14:33': ['buy', 'upward', 'accept'],
    '14:34': ['sell', 'downward', 'accept'],
    '14:35': ['buy', 'upward', 'reject_unsupported_signal'],
    '14:36': ['close', 'downward', 'accept'],
  }
  const server = createServer(async (request, response) => {
    if (request.method !== 'POST' || request.url !== '/v1/decisions') {
      response.writeHead(404).end(); return
    }
    try {
      const chunks = []
      for await (const chunk of request) chunks.push(chunk)
      const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      const parts = Object.fromEntries(payload.input[0].content.map((part) => [part.type, part]))
      const pixels = decodePixels(parts.input_image.image_url)
      const data = parts.input_json.data
      const snapshot = data.snapshot ?? data
      assert.equal(snapshot.symbol, 'AAPL')
      assert.equal(snapshot.cutoff, snapshot.candles.at(-1).timestamp)
      const minute = snapshot.cutoff.slice(11, 16)
      const expected = actions[minute]
      assert.ok(expected, `known cutoff ${minute}`)
      const reviewer = payload.questions.length === 1 && payload.questions[0].name === 'verdict'
      assert.deepEqual(payload.questions.map((item) => item.name), reviewer
        ? ['verdict'] : ['action', 'crossover', 'evidence'])
      if (reviewer) {
        assert.equal(data.analyst_answers.find((item) => item.name === 'action').choice, expected[0])
      }
      requests.push({ minute, reviewer, symbol: snapshot.symbol, cutoff: snapshot.cutoff,
        snapshot_id: snapshot.snapshot_id, pixels })
      if (!reviewer && state.failNextAnalyst) {
        state.failNextAnalyst = false
        response.writeHead(503, { 'Content-Type': 'text/plain' }).end('Offline provider failure fixture')
        return
      }
      const answers = reviewer
        ? [{ type: 'choice', name: 'verdict', choice: expected[2] }]
        : [{ type: 'choice', name: 'action', choice: expected[0] },
           { type: 'choice', name: 'crossover', choice: expected[1] },
           { type: 'choice', name: 'evidence', choice: 'sufficient' }]
      response.writeHead(200, { 'Content-Type': 'application/json' })
        .end(JSON.stringify({ model: 'smoke-model', answers }))
    } catch (error) {
      state.error = error.message
      response.writeHead(500).end('Smoke provider assertion failed')
    }
  })
  return { server, requests, state }
}

class CDP {
  constructor(url) {
    this.socket = new WebSocket(url)
    this.pending = new Map()
    this.nextId = 1
  }
  async open() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true })
      this.socket.addEventListener('error', reject, { once: true })
    })
    this.socket.addEventListener('message', ({ data }) => {
      const message = JSON.parse(String(data))
      if (!message.id) return
      const pending = this.pending.get(message.id)
      if (!pending) return
      this.pending.delete(message.id)
      if (message.error) pending.reject(new Error(message.error.message))
      else pending.resolve(message.result)
    })
  }
  send(method, params = {}) {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.socket.send(JSON.stringify({ id, method, params }))
    })
  }
  close() { this.socket.close() }
}

async function evaluate(expression) {
  const result = await pageCdp.send('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true,
  })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
  return result.result.value
}

async function value(selector) {
  return evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent?.trim() ?? null`)
}

async function fill(selector, text) {
  const found = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return false; el.value = ${JSON.stringify(String(text))};
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true })); return true })()`)
  assert.ok(found, `field ${selector} exists`)
}

async function clickButton(label) {
  const point = await evaluate(`(() => { const el = [...document.querySelectorAll('button')]
    .find((item) => item.textContent.trim() === ${JSON.stringify(label)});
    if (!el || el.disabled) return null; el.scrollIntoView({ block: 'center' });
    const r = el.getBoundingClientRect(); return { x: r.x + r.width/2, y: r.y + r.height/2 }; })()`)
  assert.ok(point, `enabled button ${label} exists`)
  await pageCdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: point.x,
    y: point.y, button: 'left', clickCount: 1 })
  await pageCdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: point.x,
    y: point.y, button: 'left', clickCount: 1 })
}

async function waitText(selector, expected, timeout = 15000) {
  return waitFor(async () => {
    const seen = await value(selector)
    return seen?.includes(expected) ? seen : false
  }, `${selector} contains ${expected}`, timeout)
}

async function state() {
  return JSON.parse(await runPython(['-m', 'backend.smoke_state', '--database', database]))
}

async function appendCandle(minute, close) {
  const previous = { 33: 9, 34: 13, 35: 8, 36: 14, 37: 7 }[minute]
  const high = Math.max(previous, close) + 1
  const low = Math.min(previous, close) - 1
  await fs.appendFile(candlesFile,
    `2026-11-09T14:${minute}:00Z,${previous},${high},${low},${close},100\n`)
  log(`Delivered completed TEST DATA candle 14:${minute} close ${close}`)
}

async function chromeReady() {
  const portFile = path.join(chromeProfile, 'DevToolsActivePort')
  const content = await waitFor(async () => existsSync(portFile)
    ? fs.readFile(portFile, 'utf8') : false, 'Chrome debugging port', 15000)
  const [port, browserPath] = content.trim().split(/\r?\n/)
  browserCdp = new CDP(`ws://127.0.0.1:${port}${browserPath}`)
  await browserCdp.open()
  return Number(port)
}

async function stopChild(record) {
  const child = record.child
  if (!child || child.exitCode !== null) return
  child.kill()
  await Promise.race([new Promise((resolve) => child.once('exit', resolve)), sleep(3000)])
  if (child.exitCode === null && process.platform === 'win32') {
    await execFileAsync('taskkill', ['/PID', String(child.pid), '/T', '/F']).catch(() => {})
  }
}

async function cleanup() {
  if (pageCdp) pageCdp.close()
  if (browserCdp) {
    await browserCdp.send('Browser.close').catch(() => {})
    browserCdp.close()
  }
  if (chrome && chrome.exitCode === null) {
    await stopChild({ child: chrome })
  }
  for (const record of [...started].reverse()) await stopChild(record)
  if (provider) await new Promise((resolve) => provider.close(resolve))
  if (!failed) {
    const relative = path.relative(runsRoot, runDir)
    assert.ok(relative.startsWith('smoke-') && !relative.includes('..') && !path.isAbsolute(relative),
      'temporary cleanup stays inside backend/data/smoke-runs')
    await fs.rm(runDir, { recursive: true, force: true })
  } else {
    log(`Failure artifacts retained at ${runDir}`)
  }
}

async function main() {
  assert.ok(existsSync(path.join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js')),
    'Vite is installed from the existing frontend lockfile')
  await fs.mkdir(runDir, { recursive: true })
  await fs.writeFile(candlesFile, [
    'timestamp,open,high,low,close,volume',
    '2026-11-09T14:30:00Z,9,11,9,10,100',
    '2026-11-09T14:31:00Z,10,13,10,12,100',
    '2026-11-09T14:32:00Z,12,12,8,9,100',
    '',
  ].join('\n'))
  await runPython(['-m', 'backend.smoke_fixture', '--database', database])
  const initial = await state().catch(() => null)
  assert.equal(initial, null, 'account is initialized only by the backend')
  const backendPort = await freePort()
  const frontendPort = await freePort()
  const providerHarness = startProvider()
  provider = providerHarness.server
  await new Promise((resolve) => provider.listen(0, '127.0.0.1', resolve))
  const providerPort = provider.address().port
  const backendEnv = {
    MARKET_DATABASE: database, MARKET_CANDLE_FILE: candlesFile,
    DECISION_CAPTURE_DIR: captures, MARKET_LIVE_FEED: '0', MARKET_PAPER_FIXTURE: '1',
    PAPER_STARTING_CASH: '1000', DECISION_PROVIDER: 'test',
    OPENAI_BASE_URL: `http://127.0.0.1:${providerPort}/v1`, OPENAI_API_KEY: '',
    PYTHONDONTWRITEBYTECODE: '1',
  }
  start(findPython(), ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1',
    '--port', String(backendPort)], backendEnv, 'FastAPI')
  start(process.execPath, [path.join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js'),
    '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'],
  { VITE_BACKEND_URL: `http://127.0.0.1:${backendPort}` }, 'Vue/Vite', path.join(root, 'frontend'))
  const frontendUrl = `http://127.0.0.1:${frontendPort}/`
  await ready(`http://127.0.0.1:${backendPort}/api/health`, 'FastAPI')
  await ready(frontendUrl, 'Vue/Vite')

  const chromePath = findChrome()
  chrome = spawn(chromePath, ['--headless=new', '--disable-gpu', '--no-first-run',
    '--no-default-browser-check', '--remote-debugging-port=0',
    `--user-data-dir=${chromeProfile}`, '--window-size=1400,1000', 'about:blank'],
  { cwd: root, windowsHide: true, stdio: 'ignore' })
  const debugPort = await chromeReady()
  const targetResponse = await fetch(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(frontendUrl)}`,
    { method: 'PUT' })
  assert.ok(targetResponse.ok, 'Chrome target opens')
  const target = await targetResponse.json()
  pageCdp = new CDP(target.webSocketDebuggerUrl)
  await pageCdp.open()
  await pageCdp.send('Page.enable')
  await pageCdp.send('Runtime.enable')
  await waitText('[data-testid="paper-cash"]', '$1000.00', 30000)
  log('Real Chrome opened the Vue dashboard with a fresh $1,000 account')

  await fill('[aria-label="Select dashboard mode"]', 'replay')
  await waitFor(async () => value('[aria-label="Select saved symbol"]'), 'recorded-session selector')
  await clickButton('Start Replay')
  await waitText('[data-testid="replay-progress"]', 'Complete', 30000)
  await fill('[aria-label="Inspect candle by UTC timestamp"]', '2026-11-09T14:32:00Z')
  await waitText('[data-testid="detail-close"]', '9')
  await fill('[aria-label="Indicator name"]', 'Smoke SMA')
  await fill('[aria-label="Indicator window"]', '3')
  await clickButton('Add indicator')
  await waitFor(async () => (await value('.indicator-list'))?.includes('Smoke SMA'), 'saved replay SMA')
  await fill('[aria-label="Smoke SMA window"]', '2')
  await clickButton('Update Smoke SMA')
  await waitText('[aria-label="Indicator values"]', '10.5 price')
  assert.equal((await state()).indicators.find((item) => item.name === 'Smoke SMA').settings.window, 2)
  log('Replay SMA window changed 3→2; displayed (12+9)/2 = 10.5')

  await fill('[aria-label="Select dashboard mode"]', 'live')
  await waitText('[data-testid="paper-cash"]', '$1000.00')
  await fill('[aria-label="Indicator name"]', 'Fast SMA')
  await fill('[aria-label="Indicator window"]', '1')
  await clickButton('Add indicator')
  await waitFor(async () => (await value('.indicator-list'))?.includes('Fast SMA'), 'fast SMA')
  await clickButton('Ask about chart')
  await waitText('[data-testid="decision-answer-action"]', 'wait', 30000)
  await waitText('[data-testid="reviewer-verdict"]', 'accept')
  assert.equal((await state()).fills, 0, 'manual chart question creates no fill')
  assert.ok(providerHarness.requests.find((item) => item.minute === '14:32' && !item.reviewer))
  log('Manual chart capture sent decoded PNG and matching AAPL/14:32 snapshot; no fill')

  providerHarness.state.failNextAnalyst = true
  await clickButton('Ask about chart')
  await waitText('[data-testid="decision-eligibility"]', 'Analyst call failed', 30000)
  assert.equal((await state()).fills, 0, 'provider failure creates no fill')
  log('Provider HTTP 503 produced visible ineligible analysis; no fill')

  await fill('[aria-label="Automation order size"]', '4')
  await clickButton('Start paper automation')
  await waitText('.decision-panel', 'Paper automation: running')
  await appendCandle(33, 13)
  await waitText('[data-testid="automation-trace"]', 'pending', 30000)
  await fill('[aria-label="Next observed price"]', '100')
  await clickButton('Supply observed price')
  await waitText('[data-testid="paper-cash"]', '$600.00')
  await waitText('[data-testid="paper-shares"]', '4')
  assert.equal((await state()).fills, 1)
  log('Approved buy 4 filled at $100: $600 cash, 4 shares')

  await fill('[aria-label="Automation order size"]', '1')
  await clickButton('Update order size')
  await waitFor(async () => {
    const response = await fetch(`http://127.0.0.1:${backendPort}/api/paper-automation?symbol=AAPL&timeframe=1m`)
    return (await response.json()).order_size === 1
  }, 'updated order size 1')
  await appendCandle(34, 8)
  await waitFor(async () => (await value('[data-testid="automation-trace"]'))?.includes('14:34:00Z')
    && (await value('[data-testid="automation-trace"]'))?.includes('pending'), 'sale order', 30000)
  await fill('[aria-label="Next observed price"]', '110')
  await clickButton('Supply observed price')
  await waitText('[data-testid="paper-cash"]', '$710.00')
  await waitText('[data-testid="paper-shares"]', '3')
  await waitText('[data-testid="paper-realized"]', '$10.00')
  await waitText('[data-testid="paper-unrealized"]', '$30.00')
  const afterSale = await state()
  assert.deepEqual([afterSale.cash, afterSale.shares, afterSale.realized,
    afterSale.unrealized, afterSale.fills], [710, 3, 10, 30, 2])
  log('Approved sell 1 filled at $110: $710 cash, 3 shares')

  await appendCandle(35, 14)
  await waitFor(async () => (await value('[data-testid="automation-trace"]'))?.includes('14:35:00Z')
    && (await value('[data-testid="automation-trace"]'))?.includes('skipped'), 'reviewer veto', 30000)
  assert.equal((await state()).fills, 2, 'veto adds no fill')
  log('Reviewer veto recorded as skipped; fill count stayed 2')

  await appendCandle(36, 7)
  await waitFor(async () => (await value('[data-testid="automation-trace"]'))?.includes('14:36:00Z')
    && (await value('[data-testid="automation-trace"]'))?.includes('pending'), 'close order', 30000)
  await fill('[aria-label="Next observed price"]', '105')
  await clickButton('Supply observed price')
  await waitText('[data-testid="paper-cash"]', '$1025.00')
  await waitText('[data-testid="paper-shares"]', '0')
  await waitText('[data-testid="paper-realized"]', '$25.00')
  await waitText('[data-testid="paper-unrealized"]', '$0.00')
  let final = await state()
  assert.deepEqual([final.cash, final.shares, final.realized, final.unrealized, final.fills],
    [1025, 0, 25, 0, 3])
  log('Approved close 3 filled at $105: $1,025 cash, 0 shares, $25 realized, $0 unrealized')

  await appendCandle(36, 7)
  const callsBeforeDuplicate = providerHarness.requests.length
  await sleep(6000)
  final = await state()
  assert.equal(final.fills, 3, 'duplicate candle adds no fill')
  assert.equal(final.orders, 3, 'duplicate candle adds no order')
  assert.equal(providerHarness.requests.length, callsBeforeDuplicate,
    'duplicate candle makes no model call')
  await clickButton('Stop paper automation')
  await waitText('.decision-panel', 'Paper automation: stopped')
  const callsBeforeStopCandle = providerHarness.requests.length
  await appendCandle(37, 14)
  await waitFor(async () => {
    const response = await fetch(`http://127.0.0.1:${backendPort}/api/history?symbol=AAPL&timeframe=1m`)
    const history = await response.json()
    return history.candles.some((candle) => candle.timestamp === '2026-11-09T14:37:00Z')
  }, 'post-Stop candle in backend history')
  await sleep(6000)
  final = await state()
  assert.equal(final.fills, 3, 'post-stop candle adds no fill')
  assert.equal(final.orders, 3, 'post-stop candle adds no order')
  assert.equal(providerHarness.requests.length, callsBeforeStopCandle,
    'post-stop candle makes no model call')
  assert.equal(providerHarness.state.error, undefined, 'provider payload assertions passed')
  assert.deepEqual(final.automation.map((item) => [item.candle_utc.slice(11, 16), item.status]),
    [['14:33', 'filled'], ['14:34', 'filled'], ['14:35', 'skipped'], ['14:36', 'filled']])
  log('Duplicate and post-Stop candles made no extra order or fill')
  log(`PASS browser=Chrome backend=FastAPI UI=Vue SQLite=isolated provider=stubbed calls=${providerHarness.requests.length}`)
}

try {
  await main()
} catch (error) {
  failed = true
  console.error(`[SmokeTest] FAIL ${error.stack || error}`)
  for (const record of started) console.error(`[SmokeTest] ${record.name} tail:\n${record.output.slice(-3000)}`)
  if (pageCdp) {
    try {
      const shot = await pageCdp.send('Page.captureScreenshot', { format: 'png' })
      await fs.writeFile(path.join(runDir, 'failure.png'), Buffer.from(shot.data, 'base64'))
    } catch { /* screenshot is best effort */ }
  }
  process.exitCode = 1
} finally {
  await cleanup()
}
