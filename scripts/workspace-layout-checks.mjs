import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import path from 'node:path'

export async function workspaceLayoutChecks({ evaluate, pageCdp, fill, clickButton, waitFor, waitText, value, state, evidenceRoot, log, exerciseIndicators }) {
  const original = await evaluate(`(()=>{const aside=document.querySelector('.workspace-sidebar');
    window.__layoutCanvas=document.querySelector('[data-testid="market-chart"] canvas');
    const sections=[...aside.children].filter(el=>el.tagName==='DETAILS');
    const original=sections.map(el=>el.open);sections.forEach(el=>el.open=false);return original})()`)
  await pageCdp.send('Emulation.setDeviceMetricsOverride', { width: 1009, height: 871, deviceScaleFactor: 1, mobile: false })
  const structure = async () => evaluate(`(()=>{const main=document.querySelector('.workspace-main'),aside=document.querySelector('.workspace-sidebar');
    return {chartLast:main.lastElementChild?.classList.contains('chart-panel'),
      toolsInSidebar:['.indicator-dock','.inspector','.feed-panel','.backtest-workspace','.attribution'].every(selector=>Boolean(aside.querySelector(selector))),
      noPageOverflow:document.documentElement.scrollWidth<=window.innerWidth+1,
      sidebarWidth:aside.getBoundingClientRect().width}})()`)
  assert.deepEqual(await structure(), { chartLast: true, toolsInSidebar: true, noPageOverflow: true, sidebarWidth: 336 })
  const point = await evaluate(`(()=>{const summary=document.querySelector('[data-testid="indicator-dock"] > summary');
    summary.scrollIntoView({block:'center'});const r=summary.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`)
  for (const type of ['mousePressed', 'mouseReleased']) await pageCdp.send('Input.dispatchMouseEvent', { type, ...point, button: 'left', clickCount: 1 })
  await waitFor(async () => evaluate(`document.querySelector('[data-testid="indicator-dock"]').open`), 'real click opens Indicators dropdown')
  assert.equal(await evaluate(`document.querySelector('.indicator-panel').getBoundingClientRect().width<=document.querySelector('.workspace-sidebar').clientWidth`), true)
  if (exerciseIndicators) {
    await waitFor(async () => evaluate(`!document.querySelector('.indicator-form button').disabled`), 'ready sidebar indicator controls')
    await fill('[aria-label="Indicator type"]', 'sma')
    await fill('[aria-label="Indicator name"]', 'Sidebar SMA')
    await fill('[aria-label="Indicator window"]', '3')
    await clickButton('Add indicator')
    await waitText('.indicator-list', 'Sidebar SMA')
    let stored = (await state()).indicators.find(row => row.name === 'Sidebar SMA')
    assert.equal(stored.settings.window, 3)
    const indicatorId = await evaluate(`fetch('/api/indicators?symbol=AAPL&timeframe=1m').then(r=>r.json()).then(data=>data.instances.find(row=>row.name==='Sidebar SMA').indicator_id)`)
    await evaluate(`document.querySelector('[data-testid="candle-inspector-dock"]').open=true`)
    await fill('[aria-label="Inspect candle by UTC timestamp"]', '2026-11-09T14:32:00Z')
    await waitText(`[data-testid="indicator-value-${indicatorId}"]`, '10.333333333333334 price')
    await fill('[aria-label="Sidebar SMA window"]', '2')
    await clickButton('Update Sidebar SMA')
    await waitText(`[data-testid="indicator-value-${indicatorId}"]`, '10.5 price')
    stored = (await state()).indicators.find(row => row.name === 'Sidebar SMA')
    assert.equal(stored.settings.window, 2)
    assert.equal((await state()).orders, 0)
  }
  assert.equal(await evaluate(`window.__layoutCanvas===document.querySelector('[data-testid="market-chart"] canvas')`), true)
  const directory = path.join(evidenceRoot, `workspace-sidebar-${Date.now()}`)
  await fs.mkdir(directory, { recursive: true })
  await evaluate(`document.querySelector('.indicator-dock').scrollIntoView({block:'nearest'});window.scrollTo(0,0)`)
  let shot = await pageCdp.send('Page.captureScreenshot', { format: 'png' })
  await fs.writeFile(path.join(directory, 'indicators_in_workspace.png'), Buffer.from(shot.data, 'base64'))
  await pageCdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
  await evaluate(`document.querySelectorAll('.workspace-sidebar > details').forEach(el=>el.open=false)`)
  const mobile = await structure()
  assert.equal(mobile.noPageOverflow, true)
  assert.equal(mobile.chartLast, true)
  assert.equal(await evaluate(`document.querySelector('.workspace-sidebar').getBoundingClientRect().bottom<=document.querySelector('.workspace-main').getBoundingClientRect().top+1`), true,
    'mobile tools precede the main chart, with no tools below it')
  await evaluate(`document.querySelector('[data-testid="market-chart"]').scrollIntoView({block:'end'})`)
  shot = await pageCdp.send('Page.captureScreenshot', { format: 'png' })
  await fs.writeFile(path.join(directory, 'mobile_chart_last.png'), Buffer.from(shot.data, 'base64'))
  await pageCdp.send('Emulation.clearDeviceMetricsOverride')
  await evaluate(`(()=>{const sections=[...document.querySelector('.workspace-sidebar').children].filter(el=>el.tagName==='DETAILS');
    const original=${JSON.stringify(original)};sections.forEach((el,i)=>el.open=original[i]);document.querySelector('.workspace-sidebar').scrollTop=0;window.scrollTo(0,0)})()`)
  await fs.writeFile(path.join(directory, 'observed.json'), JSON.stringify({ label: 'Constructed offline browser fixture; no live Yahoo/model call.',
    desktop: { width: 1009, height: 871, chart_last: true, tools_in_sidebar: true, page_overflow: false },
    mobile: { width: 390, height: 844, chart_last: true, tools_before_chart: true, page_overflow: false },
    indicator_create_update_sqlite_checked: exerciseIndicators, same_chart_canvas: true }, null, 2))
  log(`Workspace layout PASS: own Indicators dropdown, chart last, desktop/mobile fit${exerciseIndicators ? ', sidebar SMA create/update 3→2 agrees with SQLite/inspector' : ''}. Evidence: ${directory}`)
}
