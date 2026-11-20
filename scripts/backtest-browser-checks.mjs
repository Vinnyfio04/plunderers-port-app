// Actual Chrome/Vue/FastAPI operations against a separate constructed-data store.
import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import path from 'node:path'

export async function backtestChecks({ evaluate, fill, clickButton, waitFor, waitText, value, pageCdp, runPython, database, root, evidenceRoot = path.join(root, 'docs', 'evidence'), restartBackend, log }) {
  const account = () => evaluate(`fetch('/api/paper-account').then(r=>r.json())`)
  const before = await account()
  const evidence = { provenance: 'Constructed BTST bars in a disposable MARKET_DATABASE; no Yahoo or model request.', checks: [] }
  await clickButton('Backtesting')
  await waitFor(async () => evaluate(`Boolean(document.querySelector('[aria-label="Backtest Ticker"]'))`), 'opened Backtesting workspace')
  await clickButton('Use loaded chart range')
  assert.equal(await evaluate(`document.querySelector('[aria-label="Backtest Ticker"]').value`), 'AAPL')
  for (const [label, setting] of Object.entries({ Ticker: 'BTST', 'Start UTC': '2026-11-09T14:30:00', 'End UTC (exclusive)': '2026-11-09T14:37:00',
    'Fast SMA': '1', 'Slow SMA': '2', 'Shares per entry': '4', 'Starting cash ($)': '1000' })) {
    await fill(`[aria-label="Backtest ${label}"]`, setting)
  }
  const current = () => evaluate(`document.querySelector('[data-testid="backtest-run-id"]')?.textContent`)
  const get = (id) => evaluate(`fetch('/api/backtests/'+${JSON.stringify(id)}).then(r=>r.json())`)
  await clickButton('Run backtest')
  await waitText('[data-testid="backtest-notice"]', 'Simulation saved')
  await waitText('[data-testid="backtest-equity"]', '$1040.00')
  const firstId = await current(), first = await get(firstId)
  assert.deepEqual([first.summary.cash, first.summary.shares, first.summary.realized, first.summary.unrealized, first.summary.fills], [1040, 0, 40, 0, 2])
  assert.equal(await value('[data-testid="backtest-cash"]'), '$1040.00')
  assert.equal(await value('[data-testid="backtest-pnl"]'), '$40.00')
  assert.equal(await value('[data-testid="backtest-return"]'), '4.000%')
  assert.equal(await value('[data-testid="backtest-realized"]'), '$40.00')
  assert.equal(await value('[data-testid="backtest-unrealized"]'), '$0.00')
  assert.equal(await value('[data-testid="backtest-shares"]'), '0')
  const rows = await evaluate(`[...document.querySelectorAll('[data-testid="backtest-orders-table"] tbody tr')].map(row=>[...row.cells].map(cell=>cell.textContent))`)
  assert.equal(rows.length, first.orders.length)
  for (let i = 0; i < rows.length; i++) {
    const order = first.orders[i]
    assert.ok(rows[i][0].includes(`${order.order_id} · ${order.action} · ${order.status}`))
    assert.equal(rows[i][1], String(order.quantity))
    assert.ok(rows[i][3].includes(order.fill.execution_time.replace('T', ' ').replace('Z', ' UTC')))
    assert.ok(rows[i][4].includes(`$${order.fill.price.toFixed(2)}`))
  }
  const times = await value('[data-testid="backtest-decisions-table"]')
  assert.ok(times.includes('2026-11-09 14:33:00 UTC') && times.includes('2026-11-09 14:34:00 UTC'), 'chart and later decision times both displayed')
  assert.ok(await evaluate(`document.querySelector('[data-testid="backtest-equity-chart"] path').getAttribute('d').length>50`))
  await waitFor(async () => value('[data-testid="backtest-provenance"]'), 'saved source metadata')
  const persisted = JSON.parse(await runPython(['-c', `import sqlite3,json; c=sqlite3.connect(${JSON.stringify(database)}); print(c.execute('SELECT result_json FROM backtest_runs WHERE run_id=?',(${JSON.stringify(firstId)},)).fetchone()[0])`]))
  assert.deepEqual(persisted, first, 'browser-loaded result equals the SQLite result, including full trades and equity')
  evidence.checks.push({ check: 'Known example: UI / API / SQLite agree', run_id: firstId, summary: first.summary, orders: first.orders })

  // Shorter range leaves the final buy pending; do not report it as a filled trade.
  await fill('[aria-label="Backtest End UTC (exclusive)"]', '2026-11-09T14:34:00')
  await clickButton('Run backtest')
  await waitFor(async () => (await current()) !== firstId, 'second pending-order run')
  await waitText('[data-testid="backtest-counts"]', '0 fills · 1 pending')
  const pendingId = await current()
  await waitText('[data-testid="backtest-orders-table"]', 'Not filled')
  assert.equal(await value('[data-testid="backtest-equity"]'), '$1000.00')
  evidence.checks.push({ check: 'Pending end order remains unfilled', run_id: pendingId })
  await evaluate(`document.querySelector('[data-run-id="${firstId}"]').click()`)
  await waitFor(async () => (await current()) === firstId, 'reopened saved run')
  await waitText('[data-testid="backtest-equity"]', '$1040.00')
  await clickButton('Rerun saved dataset')
  await waitText('[data-testid="backtest-notice"]', 'hashes match')
  const rerunId = await current(), rerun = await get(rerunId)
  assert.notEqual(rerunId, firstId)
  assert.equal(rerun.result_hash, first.result_hash)
  assert.equal(rerun.dataset_hash, first.dataset_hash)
  evidence.checks.push({ check: 'Reopen and rerun saved data', run_id: rerunId, result_hash: rerun.result_hash, dataset_hash: rerun.dataset_hash })

  // The server saved the result but the response was lost. Retry must reuse its
  // request ID and return that one run, never silently create a second one.
  await fill('[aria-label="Backtest End UTC (exclusive)"]', '2026-11-09T14:37:00')
  await evaluate(`window.__backtestFetch=window.fetch;window.__loseBacktestOnce=true;window.fetch=async(url,options)=>{
    const response=await window.__backtestFetch(url,options);
    if(String(url)==='/api/backtests'&&options?.method==='POST'&&window.__loseBacktestOnce){
      window.__loseBacktestOnce=false;window.__lostBacktest=await response.clone().json();throw new TypeError('Constructed lost response after save');
    }return response;
  }`)
  await clickButton('Run backtest')
  await waitText('[data-testid="backtest-error"]', 'Constructed lost response after save')
  assert.equal(await current(), rerunId)
  const lost = await evaluate('window.__lostBacktest')
  const count = async () => Number(await runPython(['-c', `import sqlite3; print(sqlite3.connect(${JSON.stringify(database)}).execute('SELECT COUNT(*) FROM backtest_runs').fetchone()[0])`]))
  const savedCount = await count()
  await clickButton('Run backtest')
  await waitFor(async () => (await current()) === lost.run_id, 'idempotent retry returns the already saved result')
  assert.equal(await count(), savedCount, 'lost-response retry did not create another run')
  await evaluate('window.fetch=window.__backtestFetch')
  evidence.checks.push({ check: 'Lost response after persistence retries the same request ID, no duplicate saved run', run_id: lost.run_id })

  await fill('[aria-label="Backtest End UTC (exclusive)"]', '2026-11-09T15:30:00')
  await clickButton('Run backtest')
  await waitFor(async () => (await current()) !== lost.run_id, 'longer run for audit pagination')
  const longer = await get(await current())
  assert.ok(longer.decisions.length > 25 && longer.equity.length > 25)
  await evaluate(`document.querySelector('[aria-label="Next Decisions"]').click();document.querySelector('[aria-label="Next Equity audit"]').click()`)
  await waitFor(async () => (await value('[data-testid="backtest-decisions-table"]')).includes(longer.decisions[25].bar_time.replace('T',' ').replace('Z',' UTC')), 'second decision page exact chart time')
  assert.ok((await value('[data-testid="backtest-equity-table"]')).includes(longer.equity[25].event_id))
  evidence.checks.push({ check: 'Second audit pages show the saved chronological decision/equity records', run_id: longer.run_id, decisions: longer.decisions.length, equity_events: longer.equity.length })

  await fill('[aria-label="Backtest End UTC (exclusive)"]', '2026-11-09T14:37:00')
  await fill('[aria-label="Backtest Starting cash ($)"]', '100')
  await clickButton('Run backtest')
  await waitFor(async () => (await current()) !== rerunId, 'gap-open rejection run')
  await waitText('[data-testid="backtest-counts"]', '0 fills · 0 pending · 1 rejected')
  await waitText('[data-testid="backtest-orders-table"]', 'rejected')
  assert.equal(await value('[data-testid="backtest-equity"]'), '$100.00')
  evidence.checks.push({ check: 'Next-open gap fails cash gate; rejected order is not counted as a fill', run_id: await current() })
  await evaluate(`document.querySelector('[data-run-id="${rerunId}"]').click()`)
  await waitFor(async () => (await current()) === rerunId, 'restore earlier saved run')
  await fill('[aria-label="Backtest Starting cash ($)"]', '1000')
  await fill('[aria-label="Backtest Fast SMA"]', '2')
  await clickButton('Run backtest')
  await waitText('[data-testid="backtest-error"]', 'fast < slow')
  assert.equal(await current(), rerunId)
  await fill('[aria-label="Backtest Fast SMA"]', '1')
  await fill('[aria-label="Backtest Data mode"]', 'recorded')
  assert.equal(await evaluate(`document.querySelector('[aria-label="Backtest Interval"]').value`), '1m')
  assert.equal(await evaluate(`[...document.querySelector('[aria-label="Backtest Interval"]').options].filter(el=>!el.disabled).length`), 1)
  await clickButton('Run backtest')
  await waitText('[data-testid="backtest-error"]', 'No stored bars')
  assert.equal(await current(), rerunId)
  await fill('[aria-label="Backtest Data mode"]', 'historical_bars')
  evidence.checks.push({ check: 'Invalid SMA pair and recorded mode without original arrivals report errors, retain earlier result; recorded UI restricts interval to 1m' })

  // Empty stored ticker and a failed API response preserve the previously selected result.
  await fill('[aria-label="Backtest Ticker"]', 'EMPTY')
  await clickButton('Run backtest')
  await waitText('[data-testid="backtest-error"]', 'No stored bars')
  assert.equal(await current(), rerunId)
  await evaluate(`window.__backtestFetch=window.fetch;window.fetch=(url,options)=>String(url)==='/api/backtests'&&options?.method==='POST'
    ? Promise.resolve(new Response(JSON.stringify({detail:'Constructed service unavailable'}),{status:503,headers:{'Content-Type':'application/json'}}))
    : window.__backtestFetch(url,options)`)
  await fill('[aria-label="Backtest Ticker"]', 'BTST')
  await clickButton('Run backtest')
  await waitText('[data-testid="backtest-error"]', 'Constructed service unavailable')
  assert.equal(await current(), rerunId)
  await evaluate('window.fetch=window.__backtestFetch')
  evidence.checks.push({ check: '422 empty history and constructed 503 leave selected run unchanged' })

  // Hold an old saved-run response. Controls prevent selecting a different run mid-load;
  // chart changes neither relabel nor replace the selected backtest.
  await evaluate(`window.__backtestFetch=window.fetch;window.fetch=async(url,options)=>{
    const response=await window.__backtestFetch(url,options);
    if(String(url)==='/api/backtests/${firstId}') await new Promise(resolve=>window.__releaseBacktest=resolve);
    return response;
  };document.querySelector('[data-run-id="${firstId}"]').click()`)
  await waitFor(async () => evaluate(`typeof window.__releaseBacktest==='function'`), 'delayed saved result')
  assert.equal(await evaluate(`[...document.querySelectorAll('.backtest-saved-run')].every(el=>el.disabled)`), true)
  await fill('[aria-label="Select chart timeframe"]', '5m')
  await evaluate('window.fetch=window.__backtestFetch;window.__releaseBacktest()')
  await waitFor(async () => (await current()) === firstId, 'released saved result')
  assert.ok((await value('[data-testid="backtest-result-context"]')).startsWith('1m ·'))
  assert.equal(await evaluate(`document.querySelector('[aria-label="Backtest Ticker"]').value`), 'BTST')
  assert.equal(await value('[data-testid="backtest-equity"]'), '$1040.00')
  assert.deepEqual(await account(), before, 'backtest UI submits no paper orders and changes no cash/positions')
  await fill('[aria-label="Select chart timeframe"]', '1m')
  evidence.checks.push({ check: 'Delayed saved-run response stays tied to BTST / 1m while market chart switches; live account unchanged' })

  // Stop/start the actual backend, then reload and reopen the saved result.
  await restartBackend()
  await pageCdp.send('Page.reload')
  await waitFor(async () => evaluate(`Boolean(document.querySelector('[data-testid="paper-cash"]'))`), 'reloaded workspace')
  await clickButton('Backtesting')
  await waitFor(async () => evaluate(`Boolean(document.querySelector('[data-run-id="${firstId}"]'))`), 'saved run after reload')
  await evaluate(`document.querySelector('[data-run-id="${firstId}"]').click()`)
  await waitText('[data-testid="backtest-equity"]', '$1040.00')
  assert.deepEqual(await get(firstId), first, 'backend restart preserves the complete saved result and IDs')
  assert.deepEqual(await account(), before)
  await pageCdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
  await evaluate(`document.querySelector('.backtest-result').scrollIntoView({block:'start'})`)
  assert.ok(await evaluate(`document.documentElement.scrollWidth<=window.innerWidth+1`), 'mobile page has no horizontal overflow; tables scroll within their containers')
  assert.equal(await value('[data-testid="backtest-equity"]'), '$1040.00')
  await pageCdp.send('Emulation.clearDeviceMetricsOverride')
  evidence.checks.push({ check: 'Complete saved run and IDs survive real backend restart/browser reload; mobile result fits 390px' })
  const directory = path.join(evidenceRoot, `backtest-step6-${Date.now()}`)
  await fs.mkdir(directory, { recursive: true })
  await fs.writeFile(path.join(directory, 'observed.json'), JSON.stringify(evidence, null, 2))
  log(`Backtest workspace: known balances/trades/curve, pending order, saved/reloaded/rerun hashes, errors, chart isolation and mobile all pass. Observed evidence: ${directory}`)
}
