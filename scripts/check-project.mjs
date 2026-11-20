// Same offline check sequence locally and in CI, using existing packages only.
import { spawn, execFile } from 'node:child_process'
import { promises as fs, existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const directory = path.join(root, 'backend', 'data', 'check-runs', `check-${Date.now()}-${process.pid}`)
const localPython = 'C:\\Users\\Owner\\AppData\\Local\\Programs\\Python\\Python313\\python.exe'
const python = process.env.SMOKE_PYTHON || (process.platform === 'win32' && existsSync(localPython) ? localPython : 'python')
const env = { ...process.env, SMOKE_PYTHON: python, OPENAI_API_KEY: '', OPENAI_BASE_URL: '', CHAT_PROVIDER: 'test',
  DECISION_PROVIDER: 'test', MARKET_LIVE_FEED: '0', MARKET_CANDLE_FILE: '', PYTHONDONTWRITEBYTECODE: '1',
  MARKET_DATABASE: path.join(directory, 'isolated.sqlite3') }
env.SMOKE_EVIDENCE_DIR = path.join(directory, 'evidence')
const core = [
  ['package-integrity', python, ['-m', 'pip', 'check']],
  ['sma-reference', python, ['-m', 'backend.check_sma_engine']],
  ['accounting', python, ['-m', 'backend.check_accounting']],
  ['backtests', python, ['-m', 'backend.check_backtests']],
  ['chat-memory', python, ['-m', 'backend.check_chat_memory']],
  ['frontend-policy', process.execPath, ['--test', 'scripts/check-sma-strategy.mjs']],
  ['frontend-build', process.execPath, [path.join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js'), 'build'], path.join(root, 'frontend')],
]
const browsers = [
  ['browser-full', process.execPath, ['scripts/smoke-test.mjs']],
  ['browser-strategy', process.execPath, ['scripts/smoke-test.mjs', '--strategy-only']],
  ['browser-chat', process.execPath, ['scripts/smoke-test.mjs', '--chat-only']],
  ['browser-comparison', process.execPath, ['scripts/smoke-test.mjs', '--chat-comparison-only']],
]
const options = new Set(process.argv.slice(2))
if ([...options].some(option => !['--core-only', '--browser-only'].includes(option)) || options.size > 1) {
  throw new Error('Use no option for all checks, or --core-only / --browser-only.')
}
const steps = options.has('--core-only') ? core : options.has('--browser-only') ? browsers : [...core, ...browsers]
const summary = { mode: [...options][0] || 'all', label: 'Offline checks with constructed market/model fixtures',
  node: process.version, python, started_at: new Date().toISOString(), steps: [] }
await fs.mkdir(directory, { recursive: true })

async function execute([name, command, args, cwd = root]) {
  console.log(`[Checks] ${name}: ${command} ${args.join(' ')}`)
  const started = Date.now()
  const logFile = await fs.open(path.join(directory, `${name}.log`), 'w')
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  let expired = false, spawnError = null
  const timer = setTimeout(() => {
    expired = true
    // Only this check's process tree. Never touch a user's existing services.
    if (process.platform === 'win32' && child.pid) {
      promisify(execFile)('taskkill', ['/PID', String(child.pid), '/T', '/F']).catch(() => {})
    } else child.kill('SIGTERM')
  }, 8 * 60 * 1000)
  // A single queue keeps stdout/stderr writes ordered and finished before closing.
  let writes = Promise.resolve()
  for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => {
    process.stdout.write(chunk)
    writes = writes.then(() => logFile.write(chunk))
  })
  const exitCode = await new Promise(resolve => {
    child.once('error', error => { spawnError = error.message })
    child.once('close', code => resolve(code))
  })
  clearTimeout(timer)
  await writes
  if (spawnError) await logFile.write(`Process error: ${spawnError}\n`)
  await logFile.close()
  const passed = exitCode === 0 && !expired && !spawnError
  summary.steps.push({ name, command, args, status: passed ? 'passed' : 'failed', exit_code: exitCode,
    timeout: expired, error: spawnError, elapsed_ms: Date.now() - started })
  console.log(`[Checks] ${passed ? 'PASS' : 'FAIL'} ${name}`)
  return passed
}

try {
  for (const step of steps) {
    if (!await execute(step)) { process.exitCode = 1; break }
  }
} finally {
  summary.completed_at = new Date().toISOString()
  summary.status = summary.steps.length === steps.length && summary.steps.every(step => step.status === 'passed') ? 'passed' : 'failed'
  summary.unrun = steps.slice(summary.steps.length).map(step => step[0])
  await fs.writeFile(path.join(directory, 'summary.json'), JSON.stringify(summary, null, 2))
  console.log(`[Checks] ${summary.status.toUpperCase()} — logs and summary: ${directory}`)
}
