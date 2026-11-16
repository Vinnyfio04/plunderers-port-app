// One-command, dependency-free browser SmokeTest using installed Chrome and CDP.
import assert from 'node:assert/strict'
import { spawn, execFile } from 'node:child_process'
import { createServer } from 'node:http'
import { promises as fs, existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { inflateSync } from 'node:zlib'
import { createHash } from 'node:crypto'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const runsRoot = path.join(root, 'backend', 'data', 'smoke-runs')
const runDir = path.join(runsRoot, `smoke-${Date.now()}-${process.pid}`)
const database = path.join(runDir, 'market.sqlite3')
const candlesFile = path.join(runDir, 'candles.csv')
const captures = path.join(runDir, 'captures')
const chromeProfile = path.join(runDir, 'chrome-profile')
const execFileAsync = promisify(execFile)
const decisionsOnly = process.argv.includes('--decisions-only')
const intervalsOnly = process.argv.includes('--intervals-only')
const focused = decisionsOnly || intervalsOnly
const liveModel = decisionsOnly && process.argv.includes('--live-model')
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
    timeout: focused ? 15000 : 0,
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
  return { width, height, decodedBytes: pixels.length, sha256: createHash('sha256').update(png).digest('hex') }
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
    '20:59': ['wait', 'downward', 'accept'],
  }
  const server = createServer(async (request, response) => {
    const reply = (status, body, type='application/json') => {
      response.writeHead(status, {'Content-Type':type,'Content-Length':Buffer.byteLength(body),Connection:'keep-alive'}).end(body)
    }
    state.stage = 'received headers'
    if (request.method !== 'POST' || request.url !== '/v1/decisions') {
      reply(404,''); return
    }
    try {
      const chunks = []
      for await (const chunk of request) chunks.push(chunk)
      state.stage = `received ${Buffer.concat(chunks).length} bytes`
      const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      const parts = Object.fromEntries(payload.input[0].content.map((part) => [part.type, part]))
      const pixels = decodePixels(parts.input_image.image_url)
      state.stage = 'decoded PNG'
      const data = parts.input_json.data
      const count = (v) => 1 + (v && typeof v === 'object' ? Object.values(v).reduce((n,x) => n+count(x),0) : 0)
      assert.ok(count(data) <= 10000, 'provider JSON stays within 10,000 values')
      assert.ok(Buffer.byteLength(JSON.stringify(data)) <= 256*1024, 'provider JSON stays within byte limit')
      const snapshot = data.snapshot ?? data
      assert.ok(snapshot.candles.length <= 200, 'analysis contains at most 200 frozen candles')
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
        snapshot_id: snapshot.snapshot_id, candleCount:snapshot.candles.length, pixels })
      if (!reviewer && state.failNextAnalyst) {
        state.failNextAnalyst = false
        reply(503,'Offline provider failure fixture','text/plain')
        return
      }
      const answers = reviewer
        ? [{ type: 'choice', name: 'verdict', choice: expected[2] }]
        : [{ type: 'choice', name: 'action', choice: expected[0] },
           { type: 'choice', name: 'crossover', choice: expected[1] },
           { type: 'choice', name: 'evidence', choice: 'sufficient' }]
      reply(200,JSON.stringify({ model: 'smoke-model', answers }))
      state.stage = 'returned answers'
    } catch (error) {
      state.error = error.message
      reply(500,'Smoke provider assertion failed','text/plain')
    }
  })
  server.on('clientError',(error,socket)=> {
    if (error.code==='ECONNRESET') state.clientResets=(state.clientResets ?? 0)+1
    else state.error=`HTTP parser: ${error.code}`
    socket.destroy()
  })
  server.smokeState = state
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
      if (!message.id) { this.onEvent?.(message); return }
      const pending = this.pending.get(message.id)
      if (!pending) return
      this.pending.delete(message.id)
      clearTimeout(pending.timer)
      if (message.error) pending.reject(new Error(message.error.message))
      else pending.resolve(message.result)
    })
  }
  send(method, params = {}) {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`Browser command timed out: ${method}`))
      }, 15000)
      this.pending.set(id, { resolve, reject, timer })
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

async function waitExactText(selector,expected,timeout=15000) {
  return waitFor(async()=>(await value(selector))===expected,`${selector} equals ${expected}`,timeout)
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
  if (!focused) {
    log(await runPython(['-m', 'backend.check_continuous']))
    log(await runPython(['-m', 'backend.check_recent_history']))
    log(await runPython(['-m', 'backend.check_provider_failures']))
  }
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
  if (decisionsOnly) {
    const rows = ['timestamp,open,high,low,close,volume']
    for (let day=9;day<=13;day++) for (let minute=0;minute<390;minute++) {
      const timestamp = new Date(Date.UTC(2026,10,day,14,30+minute)).toISOString().replace('.000Z','Z')
      rows.push(`${timestamp},10,13,8,${minute%2 ? 9 : 12},100`)
    }
    await fs.writeFile(candlesFile,rows.join('\n')+'\n')
  }
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
  if (liveModel) {
    assert.ok(process.env.OPENAI_API_KEY,'live model requires a privately loaded OPENAI_API_KEY')
    Object.assign(backendEnv,{DECISION_PROVIDER:'openai',OPENAI_BASE_URL:'https://api.openai.com/v1',OPENAI_API_KEY:process.env.OPENAI_API_KEY})
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
  if (intervalsOnly) {
    await continuousSessionChecks()
    log('PASS focused interval loading and live continuity; no model calls, benchmark or automation regression')
    return
  }
  if (decisionsOnly) {
    await chartAnalysisChecks(providerHarness)
    log(`PASS focused ${liveModel ? 'LIVE model' : 'offline'} chart analysis; unrelated replay, automation and scale regressions not run`)
    return
  }
  if (process.argv.includes('--history-only')) {
    await continuousSessionChecks()
    log('PASS focused company-history browser checks; decision/paper regression not run in this mode')
    return
  }

  await fill('[aria-label="Select dashboard mode"]', 'replay')
  await waitFor(async () => value('[aria-label="Select saved symbol"]'), 'recorded-session selector')
  await waitFor(async()=>evaluate(`Boolean(document.querySelector('[aria-label="Replay start UTC"]')?.value && document.querySelector('[aria-label="Replay end UTC"]')?.value)`),'loaded recorded-session range')
  await waitFor(async()=>evaluate(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Start Replay' && !b.disabled)`),'ready Replay control')
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
  await waitFor(async()=>evaluate(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Add indicator' && !b.disabled)`),'ready live indicator panel')
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
  await continuousSessionChecks()
  log(`PASS browser=Chrome backend=FastAPI UI=Vue SQLite=isolated provider=stubbed calls=${providerHarness.requests.length}`)
}

async function chartAnalysisChecks(harness) {
  await waitFor(async()=>evaluate(`document.querySelectorAll('[aria-label="Inspect candle by UTC timestamp"] option').length===500`),'500 recent bars from 1,950 fixture candles')
  for (const [name,window] of [['Fast SMA',1],['Slow SMA',2]]) {
    await waitFor(async()=>evaluate(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Add indicator' && !b.disabled)`),'ready indicator controls')
    await fill('[aria-label="Indicator name"]',name)
    await fill('[aria-label="Indicator window"]',window)
    await clickButton('Add indicator')
    await waitFor(async()=>(await value('.indicator-list'))?.includes(name),`${name} saved`)
  }
  await waitFor(async()=>evaluate(`!document.querySelector('[data-testid="ask-about-chart"]').disabled`),'ready chart analysis')
  const saved = async () => JSON.parse(await runPython(['-c',
    `import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); c.row_factory=sqlite3.Row; print(json.dumps([dict(r) for r in c.execute('SELECT d.decision_id,d.model,d.reviewer_model,d.image_sha256,d.answers_json,d.reviewer_answers_json,d.analyst_error,d.reviewer_error,s.snapshot_json FROM decision_records d JOIN decision_snapshots s USING(snapshot_id) ORDER BY d.rowid')]))`,database]))
  await clickButton('Ask about chart')
  if (liveModel) {
    await waitFor(async()=>value('[data-testid="decision-response"]'),'one live model result',75000)
    const rows = await saved()
    assert.equal(rows.length,1,'one live analysis request, without retry')
    const row=rows[0]
    assert.equal(row.analyst_error,null,'live analyst request succeeded')
    assert.equal(row.reviewer_error,null,'reviewer has no transport error')
    const answers=JSON.parse(row.answers_json)
    for (const answer of answers) await waitText(`[data-testid="decision-answer-${answer.name}"]`,String(answer.choice))
    const preview=await evaluate(`document.querySelector('[data-testid="decision-preview"]').src`)
    assert.equal(decodePixels(preview).sha256,row.image_sha256)
    assert.equal(JSON.parse(row.snapshot_json).candles.length,200)
    const account=await state()
    assert.deepEqual([account.cash,account.shares,account.orders,account.fills],[1000,0,0,0])
    log(`LIVE model against labeled synthetic candles: ${JSON.stringify({decision:row.decision_id,model:row.model,reviewer_model:row.reviewer_model,answers,review:JSON.parse(row.reviewer_answers_json),python:JSON.parse(row.snapshot_json).python_crossover.signal})}`)
    log('Live answers match SQLite; decodable preview hash matches saved PNG; account unchanged')
    return
  }
  await waitText('[data-testid="decision-answer-action"]','wait',30000)
  await waitText('[data-testid="reviewer-verdict"]','accept')
  await waitText('[data-testid="decision-cutoff"]','2026-11-13T20:59:00Z')
  assert.equal(harness.requests.length,2,'one call per role')
  assert.ok(harness.requests.every(r=>r.candleCount===200 && r.cutoff==='2026-11-13T20:59:00Z'))
  assert.equal(harness.requests[0].snapshot_id,harness.requests[1].snapshot_id)
  assert.equal(harness.requests[0].pixels.sha256,harness.requests[1].pixels.sha256)
  const rows = await saved()
  assert.equal(rows[0].image_sha256,harness.requests[0].pixels.sha256,'SQLite capture hash matches actual decoded provider PNG')
  const preview = await evaluate(`document.querySelector('[data-testid="decision-preview"]').src`)
  assert.equal(decodePixels(preview).sha256,rows[0].image_sha256,'visible preview matches saved PNG')
  const snapshot = JSON.parse(rows[0].snapshot_json)
  assert.equal(snapshot.candles.length,200)
  assert.equal(snapshot.python_crossover.signal,'downward')
  assert.equal(JSON.parse(rows[0].answers_json).find(a=>a.name==='action').choice,'wait')
  assert.equal(JSON.parse(rows[0].reviewer_answers_json)[0].choice,'accept')
  log('1,950 source candles → 500 recent bars → 200 frozen candles; decoded PNG/preview/SQLite hashes match; wait/downward/accept displayed')

  harness.state.failNextAnalyst = true
  await clickButton('Ask about chart')
  await waitText('[data-testid="decision-eligibility"]','Analyst call failed',30000)
  assert.equal(harness.requests.length,3,'failed analyst not retried and reviewer skipped')
  assert.ok((await saved())[1].analyst_error.includes('503'))
  await clickButton('Ask about chart')
  await waitText('[data-testid="reviewer-verdict"]','accept',30000)
  assert.equal(harness.requests.length,5,'manual recovery makes exactly two fresh role calls')
  log('Provider 503 is visible and saved; a manual retry recovers without automatic retries')

  await evaluate(`window.__chartOriginalFetch=window.fetch; window.fetch=async(...args)=>{
    const response=await window.__chartOriginalFetch(...args);
    if(String(args[0]).includes('/api/decision-snapshots')) await new Promise(resolve=>{window.__releaseChartSnapshot=resolve});
    return response;
  }`)
  await clickButton('Ask about chart')
  await waitFor(async()=>evaluate(`typeof window.__releaseChartSnapshot==='function'`),'delayed snapshot ready')
  assert.equal(await evaluate(`Boolean(document.querySelector('[data-testid="decision-preview"]'))`),false,'old preview cleared at request start')
  await fill('[aria-label="Select chart timeframe"]','5m')
  await evaluate(`window.fetch=window.__chartOriginalFetch; window.__releaseChartSnapshot()`)
  await waitText('[data-testid="decision-error"]','chart changed',15000)
  assert.equal(harness.requests.length,5,'changed chart is not sent to provider')
  const account = await state()
  assert.deepEqual([account.cash,account.shares,account.orders,account.fills],[1000,0,0,0])
  assert.equal(harness.state.error,undefined)
  log('Switch during snapshot rejects stale capture; account remains $1,000 / 0 shares / 0 orders / 0 fills')
  const captureIsolation = await evaluate(`(async()=>{
    const {createCandleChart}=await import('/src/chartAdapter.js');
    const container=document.createElement('div');
    container.style.cssText='position:fixed;left:-10000px;top:0;width:640px;height:500px';
    document.body.append(container);
    const original=[12,13,9].map((close,i)=>({timestamp:'2026-11-13T20:'+String(57+i)+':00Z',open:close,high:close+1,low:close-1,close,volume:100}));
    const revised=original.map(c=>({...c,open:c.open+100,high:c.high+100,low:c.low+100,close:c.close+100}));
    const adapter=createCandleChart(container,original,()=>{});
    try {
      const baseline=await adapter.captureThrough(original[2].timestamp,[],original);
      const olderIndicator={name:'TEST older-only SMA',values:[{timestamp:'2026-11-09T14:30:00Z',value:500}]};
      const bounded=await adapter.captureThrough(original[2].timestamp,[olderIndicator],original);
      const pending=adapter.captureThrough(original[2].timestamp,[],original);
      adapter.setCandles(revised);
      const frozen=await pending;
      const latest=await adapter.captureThrough(original[2].timestamp,[],revised);
      return {frozenUnchanged:baseline===frozen,revisionVisibleAfterCapture:latest!==frozen,olderIndicatorsDoNotExtendRange:bounded===baseline};
    } finally {adapter.destroy();container.remove()}
  })()`)
  assert.deepEqual(captureIsolation,{frozenUnchanged:true,revisionVisibleAfterCapture:true,olderIndicatorsDoNotExtendRange:true})
  log('Concurrent bulk refresh preserves frozen PNG pixels and applies revised prices after capture')
}

async function intervalLoadingChecks(apiUrl,db,traffic) {
  await waitFor(async()=>['5m','15m','1h','1d'].every(interval=>traffic.requests.some(r=>{
    const q=new URL(r.url).searchParams
    return q.get('timeframe')===interval && q.get('recent')==='false' && traffic.finished.has(r.id)
  })),'four bounded SQLite prefetches')
  assert.ok(traffic.requests.every(r=>new URL(r.url).searchParams.get('limit')==='500'))
  await evaluate(`window.__intervalCanvas=document.querySelector('[data-testid="market-chart"] canvas');
    window.__intervalFetch=window.fetch;
    window.fetch=(...args)=>{
      const q=new URL(args[0],location.href).searchParams;
      if(String(args[0]).includes('/api/history?') && q.get('recent')==='true' && q.get('timeframe')==='5m')
        return new Promise(resolve=>{window.__releaseInterval=()=>resolve(window.__intervalFetch(...args))});
      return window.__intervalFetch(...args);
    };`)
  const began=Date.now()
  await fill('[aria-label="Select chart timeframe"]','5m')
  await waitText('[data-testid="detail-close"]','100')
  const cachedMilliseconds=Date.now()-began
  assert.ok(cachedMilliseconds<1500,`cached switch under 1.5s while HTTP is held: ${cachedMilliseconds}ms`)
  assert.ok(await evaluate(`Boolean(window.__releaseInterval) && document.querySelectorAll('[aria-label="Inspect candle by UTC timestamp"] option').length===390`))
  assert.equal(await evaluate(`window.__intervalCanvas===document.querySelector('[data-testid="market-chart"] canvas')`),true,'one chart instance reused')
  await evaluate(`window.fetch=window.__intervalFetch;window.__releaseInterval()`)
  await waitExactText('[data-testid="socket-status"]','connected')
  for (const interval of ['15m','1h','1d','1m']) {
    await fill('[aria-label="Select chart timeframe"]',interval)
    await waitText('[data-testid="feed-interval"]',interval)
    await waitText('[data-testid="detail-close"]','100')
    await waitExactText('[data-testid="socket-status"]','connected')
    assert.equal(await evaluate(`window.__intervalCanvas===document.querySelector('[data-testid="market-chart"] canvas')`),true)
  }
  assert.equal(traffic.frames.filter(m=>m.type==='history').length,0,'valid HTTP cursors avoid duplicate socket history snapshots')
  log(`All intervals use bounded prefetch; cached 5m renders in ${cachedMilliseconds}ms with foreground HTTP held; one chart canvas reused; no duplicate socket snapshot`)

  const point=await evaluate(`(()=>{const el=document.querySelector('[data-testid="market-chart"]');el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`)
  await pageCdp.send('Input.dispatchMouseEvent',{type:'mouseWheel',...point,deltaX:0,deltaY:-3000,modifiers:8})
  await waitFor(async()=>evaluate(`document.querySelectorAll('[aria-label="Inspect candle by UTC timestamp"] option').length===1950`),'older pages remain accessible')
  assert.ok(traffic.requests.some(r=>new URL(r.url).searchParams.has('before')))
  for (const [seconds,price,total] of [[5,101,4],[20,103,9]]) {
    const response=await fetch(`${apiUrl}/api/market-fixture`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      source_time:`2026-11-16T14:30:${String(seconds).padStart(2,'0')}Z`,receipt_time:`2026-11-16T14:30:${String(seconds+1).padStart(2,'0')}Z`,price,volume:total})})
    assert.equal(response.status,200)
    await waitText('[data-testid="detail-close"]',String(price))
  }
  await fill('[aria-label="Select chart timeframe"]','5m')
  await waitText('[data-testid="detail-close"]','103')
  await waitExactText('[data-testid="socket-status"]','connected')
  await evaluate(`window.__intervalFetch=window.fetch;window.fetch=(...args)=>{
    const q=new URL(args[0],location.href).searchParams;
    if(String(args[0]).includes('/api/history?') && q.get('recent')==='true' && q.get('timeframe')==='1m')
      return new Promise(resolve=>{window.__releaseInterval=()=>resolve(window.__intervalFetch(...args))});
    return window.__intervalFetch(...args);
  }`)
  await fill('[aria-label="Select chart timeframe"]','1m')
  await waitText('[data-testid="detail-close"]','103')
  assert.ok(await evaluate(`Boolean(window.__releaseInterval)`),'live value is restored from cache before HTTP')
  await evaluate(`window.fetch=window.__intervalFetch;window.__releaseInterval()`)
  await waitExactText('[data-testid="socket-status"]','connected')
  const record=JSON.parse(await runPython(['-c',`import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); r=c.execute('SELECT close,volume FROM candles_1m ORDER BY minute_start DESC LIMIT 1').fetchone(); print(json.dumps(dict(close=r[0],volume=r[1],orders=c.execute('SELECT COUNT(*) FROM paper_orders').fetchone()[0])))`,db]))
  assert.deepEqual(record,{close:103,volume:null,orders:0})
  log('Older 1,950 bars remain accessible; live 101→103 update and Unknown opening volume match SQLite, survive switches and create no orders')
}

async function continuousSessionChecks() {
  const continuousDb = path.join(runDir, 'market.db')
  await runPython(['-m','backend.continuous_fixture','--database',continuousDb])
  const apiPort = await freePort()
  const uiPort = await freePort()
  const apiUrl = `http://127.0.0.1:${apiPort}`
  const env = { MARKET_DATABASE:continuousDb, MARKET_LIVE_FEED:'0', MARKET_CANDLE_FILE:'',
    MARKET_TEST_FEED:'0', MARKET_MANUAL_TEST_FEED:'1', MARKET_PAPER_FIXTURE:'1', PAPER_STARTING_CASH:'1000',
    OPENAI_API_KEY:'', PYTHONDONTWRITEBYTECODE:'1' }
  const launch = () => start(findPython(),['-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',String(apiPort)],env,'Continuous FastAPI')
  let backend = launch()
  start(process.execPath,[path.join(root,'frontend','node_modules','vite','bin','vite.js'),'--host','127.0.0.1','--port',String(uiPort),'--strictPort'],
    {VITE_BACKEND_URL:apiUrl},'Continuous Vue',path.join(root,'frontend'))
  await ready(`${apiUrl}/api/health`,'Continuous FastAPI')
  await ready(`http://127.0.0.1:${uiPort}/`,'Continuous Vue')
  await pageCdp.send('Page.addScriptToEvaluateOnNewDocument',{source:`
    window.__axisLabels = [];
    const original = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function(text,...args) {
      if (/\\d{2}\\/\\d{2}\\/\\d{4} \\d{2}:\\d{2}/.test(String(text))) {
        window.__axisLabels.push(String(text)); if (window.__axisLabels.length>500) window.__axisLabels.shift();
      }
      return original.call(this,text,...args);
    };`})
  const intervalTraffic = {requests:[],finished:new Set(),frames:[]}
  if (intervalsOnly) {
    await pageCdp.send('Network.enable')
    pageCdp.onEvent = ({method,params}) => {
      if (method==='Network.requestWillBeSent' && params.request.url.includes('/api/history?')) {
        intervalTraffic.requests.push({id:params.requestId,url:params.request.url})
      }
      if (method==='Network.loadingFinished') intervalTraffic.finished.add(params.requestId)
      if (method==='Network.webSocketFrameReceived') {
        try { intervalTraffic.frames.push(JSON.parse(params.response.payloadData)) } catch {}
      }
    }
  }
  await pageCdp.send('Page.navigate',{url:`http://127.0.0.1:${uiPort}/`})
  await waitText('[data-testid="market-status"]','Market closed')
  await waitText('[data-testid="detail-close"]','100')
  await waitExactText('[data-testid="socket-status"]','connected')
  if (intervalsOnly) {
    await intervalLoadingChecks(apiUrl,continuousDb,intervalTraffic)
    return
  }
  const fullHistory=await fetch(`http://127.0.0.1:${uiPort}/api/history?symbol=AAPL&timeframe=1m&recent=true`,{signal:AbortSignal.timeout(10000)})
  assert.equal(fullHistory.status,200,'full history passes through Vue proxy')
  assert.equal((await fullHistory.json()).candles.length,1950,'all five saved sessions are available while closed')
  await pageCdp.send('Network.enable')
  await pageCdp.send('Network.setBlockedURLs',{urls:['*/api/indicator-types','*/api/indicators?*']})
  const selectCompany=async()=>{
    const point=await evaluate(`(()=>{const el=document.querySelector('[data-testid="watchlist-AAPL"]');el.scrollIntoView();const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`)
    await pageCdp.send('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1})
    await pageCdp.send('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1})
  }
  await selectCompany()
  await waitText('[data-testid="indicator-error"]','could not be loaded')
  await waitText('[data-testid="detail-close"]','100')
  await waitText('[data-testid="market-status"]','Market closed')
  await waitExactText('[data-testid="socket-status"]','connected')
  await pageCdp.send('Network.setBlockedURLs',{urls:[]})
  await selectCompany()
  await waitText('[data-testid="detail-close"]','100')
  log('Closed-market company selection loaded 1,950 saved candles through Vue proxy, including with indicator requests unavailable')
  const deliver = async (source,receipt,price,volume) => {
    const r=await fetch(`${apiUrl}/api/market-fixture`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({source_time:source,receipt_time:receipt,price,volume})})
    assert.ok(r.ok, 'fixture accepted')
    return r.json()
  }
  await deliver('2026-11-16T14:30:05Z','2026-11-16T14:30:06Z',101,4)
  await waitText('[data-testid="market-status"]','Market open')
  await waitText('[data-testid="detail-close"]','101')
  let h=await (await fetch(`${apiUrl}/api/history`)).json()
  assert.deepEqual(h.candles.slice(-2).map(c=>c.timestamp),['2026-11-13T20:59:00Z','2026-11-16T14:30:00Z'])
  // Leave room for the first new-session date label at the chart's right edge.
  const panForLabels=async()=>{
    const p=await evaluate(`(()=>{const el=document.querySelector('[data-testid="market-chart"]');el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return {x:r.x+r.width*.7,y:r.y+r.height*.45,dx:Math.min(220,r.width*.35)}})()`)
    await pageCdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:p.x,y:p.y})
    await pageCdp.send('Input.dispatchMouseEvent',{type:'mousePressed',x:p.x,y:p.y,button:'left',clickCount:1})
    for(let i=1;i<=8;i++) await pageCdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:p.x-p.dx*i/8,y:p.y,button:'left',buttons:1})
    await pageCdp.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:p.x-p.dx,y:p.y,button:'left',clickCount:1})
  }
  await panForLabels()
  await waitFor(async()=>evaluate(`window.__axisLabels.some(x=>x.includes('11/13/2026')) && window.__axisLabels.some(x=>x.includes('11/16/2026'))`),'dated axis labels on both days')
  await evaluate('window.__axisLabels = []')
  await pageCdp.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false})
  await panForLabels()
  await waitFor(async()=>evaluate(`window.__axisLabels.some(x=>x.includes('11/16/2026 14:30'))`),'mobile dated axis')
  await pageCdp.send('Emulation.clearDeviceMetricsOverride')
  await deliver('2026-11-16T14:30:20Z','2026-11-16T14:30:21Z',103,9)
  await waitText('[data-testid="detail-close"]','103')
  await deliver('2026-11-16T14:30:20Z','2026-11-16T14:30:22Z',103,9)
  h=await (await fetch(`${apiUrl}/api/history`)).json()
  assert.equal(h.candles.length,1951)
  await new Promise((resolve)=>{ backend.once('exit',resolve); backend.kill() })
  await waitExactText('[data-testid="socket-status"]','disconnected')
  backend=launch()
  await ready(`${apiUrl}/api/health`,'Restarted continuous FastAPI')
  await waitExactText('[data-testid="socket-status"]','connected',30000)
  await deliver('2026-11-16T14:30:40Z','2026-11-16T14:30:41Z',104,11)
  await waitText('[data-testid="detail-close"]','104')
  const latency=[]
  await evaluate(`window.__visibleTicks = []; new MutationObserver(() => {
    const value=Number(document.querySelector('[data-testid="detail-close"]')?.textContent);
    if (value>=105) window.__visibleTicks.push({value,at:Date.now()});
  }).observe(document.querySelector('[data-testid="detail-close"]'),{childList:true,subtree:true,characterData:true})`)
  const sent=new Map()
  const pending=[]
  for (let i=0;i<100;i++) {
    const fraction=String(i).padStart(3,'0')
    const price=105+i/1000
    pending.push(deliver(`2026-11-16T14:30:42.${fraction}Z`,`2026-11-16T14:30:43.${fraction}Z`,price,12+i)
      .then(result=>sent.set(price,result.committed_at_ms)))
    await sleep(10)
  }
  await Promise.all(pending)
  await waitText('[data-testid="detail-close"]','105.099')
  for (const tick of await evaluate('window.__visibleTicks')) {
    if (sent.has(tick.value)) latency.push(tick.at-sent.get(tick.value))
  }
  assert.ok(latency.length>=2,'browser observed coalesced stress updates')
  latency.sort((a,b)=>a-b)
  const p95=latency[Math.floor(latency.length*.95)]
  assert.ok(p95<=1000,`browser tick p95 ${p95}ms <=1000`)
  log(`Browser stream stress: 100 observations at 100/s; visible p95=${p95}ms`)
  const account=await (await fetch(`${apiUrl}/api/paper-account`)).json()
  assert.equal(account.orders.length,0)
  log('Continuous browser: Friday/Monday adjacent, dated desktop/mobile axis, in-place update, duplicate, backend restart/reconnect, zero orders')
}

try {
  await main()
} catch (error) {
  failed = true
  console.error(`[SmokeTest] FAIL ${error.stack || error}`)
  if (provider?.smokeState) console.error(`[SmokeTest] Provider boundary state: ${JSON.stringify(provider.smokeState)}`)
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
