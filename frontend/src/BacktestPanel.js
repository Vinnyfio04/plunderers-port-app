import { computed, h, ref } from 'vue'

const money = (value) => value == null ? 'Unavailable' : `${value < 0 ? '-' : ''}$${Math.abs(value).toFixed(2)}`
const utc = (value) => value ? value.replace('T', ' ').replace(/(?:\.000)?Z$/, ' UTC') : '—'
const modeName = (value) => value === 'recorded' ? 'Recorded availability · 1m' : 'Historical bars · fixed vintage'
const percent = (value) => value == null ? 'Unavailable' : `${value.toFixed(3)}%`
const id = () => `backtest-${crypto.randomUUID()}`

// No inferred returns or profit statistics: monetary values come from the saved result.
function equityPlot(run) {
  const rows = [{ timestamp: run.settings.start, equity: run.summary.initial_cash }, ...run.equity]
  const values = rows.filter((row) => Number.isFinite(row.equity)).map((row) => row.equity)
  let low = Math.min(...values), high = Math.max(...values)
  const padding = Math.max((high - low) * .12, .01)
  low -= padding; high += padding
  const beginning = Date.parse(run.settings.start), finish = Date.parse(run.settings.end)
  const x = (time) => 80 + (Date.parse(time) - beginning) / (finish - beginning) * 800
  const y = (value) => 218 - (value - low) / (high - low) * 188
  let gap = true
  const path = rows.map((row) => {
    if (row.equity == null) { gap = true; return '' }
    const command = gap ? 'M' : 'L'
    gap = false
    return `${command}${x(row.timestamp).toFixed(2)},${y(row.equity).toFixed(2)}`
  }).join(' ')
  return { path, baseline: y(run.summary.initial_cash), low, high }
}

export default {
  name: 'BacktestPanel',
  props: { chartContext: { type: Object, required: true } },
  setup(props) {
    const opened = ref(false)
    const draft = ref({ symbol: 'AAPL', timeframe: '1m', data_mode: 'historical_bars', start: '', end: '',
      fast_window: '5', slow_window: '20', quantity: '1', starting_cash: '1000' })
    const result = ref(null)
    const provenance = ref(null)
    const provenanceError = ref('')
    const saved = ref([])
    const savedOffset = ref(0)
    const loadingList = ref(false)
    const busy = ref(false)
    const error = ref('')
    const listError = ref('')
    const notice = ref('')
    const pages = ref({ orders: 0, decisions: 0, equity: 0 })
    const plot = computed(() => result.value ? equityPlot(result.value) : null)
    let listGeneration = 0
    let resultGeneration = 0
    // Keep the same ID after an uncertain network outcome, so Retry cannot save a duplicate.
    let pendingRequest = null

    async function request(url, options = {}) {
      const response = await fetch(url, { ...options, signal: AbortSignal.timeout(120000) })
      const payload = await response.json()
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : `Backtest request failed (${response.status}).`)
      return payload
    }
    async function list(offset = savedOffset.value) {
      const generation = ++listGeneration
      loadingList.value = true; listError.value = ''
      try {
        const data = await request(`/api/backtests?limit=10&offset=${offset}`)
        if (generation !== listGeneration) return
        saved.value = data.runs; savedOffset.value = offset
      } catch (failure) {
        if (generation === listGeneration) listError.value = failure.message
      } finally { if (generation === listGeneration) loadingList.value = false }
    }
    function show(run) {
      result.value = run
      provenance.value = null; provenanceError.value = ''
      pages.value = { orders: 0, decisions: 0, equity: 0 }
      request(`/api/backtests/${encodeURIComponent(run.run_id)}/dataset`).then((dataset) => {
        if (result.value?.run_id !== run.run_id) return
        const sources = [...new Set(dataset.bars.map((bar) => bar.source).filter(Boolean))]
        provenance.value = { ...dataset.provenance, sources: sources.join(', ') || 'See frozen dataset' }
      }).catch((failure) => {
        if (result.value?.run_id === run.run_id) provenanceError.value = failure.message
      })
    }
    async function load(runId) {
      const generation = ++resultGeneration
      busy.value = true; error.value = ''; notice.value = 'Loading saved result…'
      try {
        const run = await request(`/api/backtests/${encodeURIComponent(runId)}`)
        if (generation !== resultGeneration) return
        show(run); notice.value = 'Saved result loaded. Draft settings above do not change this result.'
      } catch (failure) {
        if (generation === resultGeneration) { error.value = failure.message; notice.value = '' }
      } finally { if (generation === resultGeneration) busy.value = false }
    }
    function context() {
      const chart = props.chartContext
      draft.value = { ...draft.value, symbol: chart.symbol, timeframe: chart.timeframe,
        data_mode: 'historical_bars', start: chart.start?.slice(0, 19) ?? '', end: chart.end?.slice(0, 19) ?? '',
        ...(chart.fast ? { fast_window: String(chart.fast), slow_window: String(chart.slow), quantity: String(chart.quantity) } : {}) }
      notice.value = 'Copied loaded chart range in UTC (including bars outside the current zoom). Review settings before running; historical bars use a fixed data vintage.'
    }
    async function run(event, rerun = false) {
      event?.preventDefault()
      if (busy.value) return
      const parent = rerun ? result.value : null
      const payload = rerun ? {} : { ...draft.value,
        symbol: draft.value.symbol.trim().toUpperCase(), start: `${draft.value.start}Z`, end: `${draft.value.end}Z`,
        fast_window: Number(draft.value.fast_window), slow_window: Number(draft.value.slow_window),
        quantity: Number(draft.value.quantity), starting_cash: Number(draft.value.starting_cash) }
      const url = parent ? `/api/backtests/${encodeURIComponent(parent.run_id)}/rerun` : '/api/backtests'
      const fingerprint = JSON.stringify({ url, payload })
      if (pendingRequest?.fingerprint !== fingerprint) pendingRequest = { fingerprint, requestId: id() }
      const generation = ++resultGeneration
      busy.value = true; error.value = ''; notice.value = 'Running isolated simulation…'
      try {
        const data = await request(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, request_id: pendingRequest.requestId }) })
        if (generation !== resultGeneration) return
        show(data); pendingRequest = null
        notice.value = parent
          ? data.result_hash === parent.result_hash && data.dataset_hash === parent.dataset_hash ? 'Rerun saved: result and dataset hashes match the earlier run.' : 'Rerun saved, but its hashes differ from the earlier run. Inspect both records.'
          : 'Simulation saved. The market chart and paper account remain independent.'
        await list(0)
      } catch (failure) {
        if (generation === resultGeneration) { error.value = failure.message; notice.value = '' }
      } finally { if (generation === resultGeneration) busy.value = false }
    }
    function input(label, key, options = {}) {
      return h('label', [h('span', label), h('input', { 'aria-label': `Backtest ${label}`, value: draft.value[key],
        required: true, disabled: busy.value, ...options,
        onInput: (event) => { draft.value = { ...draft.value, [key]: event.target.value } } })])
    }
    function select(label, key, choices) {
      return h('label', [h('span', label), h('select', { 'aria-label': `Backtest ${label}`, value: draft.value[key], disabled: busy.value,
        onChange: (event) => { draft.value = { ...draft.value, [key]: event.target.value,
          ...(key === 'data_mode' && event.target.value === 'recorded' ? { timeframe: '1m' } : {}) } } },
      choices.map(([value, text]) => h('option', { value, disabled: key === 'timeframe' && draft.value.data_mode === 'recorded' && value !== '1m' }, text)))])
    }
    function metric(label, value, key) {
      return h('div', [h('dt', label), h('dd', { 'data-testid': `backtest-${key}` }, value)])
    }
    function table(key, title, headers, rows, render) {
      const page = pages.value[key], start = page * 25
      return h('section', { class: 'backtest-table-section', 'aria-label': title }, [
        h('div', { class: 'backtest-table-heading' }, [h('h3', `${title} · ${rows.length}`),
          h('div', { class: 'backtest-pages' }, [
            h('button', { class: 'secondary-button', type: 'button', disabled: page === 0,
              'aria-label': `Previous ${title}`, onClick: () => { pages.value[key]-- } }, 'Previous'),
            h('span', rows.length ? `${start + 1}–${Math.min(start + 25, rows.length)} of ${rows.length}` : '0 rows'),
            h('button', { class: 'secondary-button', type: 'button', disabled: start + 25 >= rows.length,
              'aria-label': `Next ${title}`, onClick: () => { pages.value[key]++ } }, 'Next'),
          ]),
        ]),
        rows.length ? h('div', { class: 'table-scroll', tabindex: '0', 'aria-label': `${title} scrollable table` }, [
          h('table', { 'data-testid': `backtest-${key}-table` }, [
            h('thead', [h('tr', headers.map((label) => h('th', { scope: 'col' }, label)))]),
            h('tbody', rows.slice(start, start + 25).map((row) => h('tr', render(row).map((cell) => h('td', cell))))),
          ]),
        ]) : h('p', `No ${title.toLowerCase()} in this run.`),
      ])
    }
    return () => h('details', { class: 'backtest-workspace', 'data-testid': 'backtest-workspace', onToggle: (event) => {
      if (event.target.open && !opened.value) { opened.value = true; list(0) }
    } }, [
      h('summary', [h('span', 'Backtesting'), h('small', 'Isolated SMA simulation')]),
      opened.value ? h('div', { class: 'backtest-body' }, [
        h('div', { class: 'backtest-heading' }, [
          h('div', [h('p', { class: 'eyebrow' }, 'STRATEGY LAB'), h('h2', 'Measure a saved-history strategy'),
            h('p', 'Each run starts flat in a separate simulated account. It cannot submit paper or brokerage orders.')]),
          h('button', { class: 'secondary-button', type: 'button', disabled: busy.value || !props.chartContext.start,
            onClick: context }, 'Use loaded chart range'),
        ]),
        h('form', { class: 'backtest-form', onSubmit: run }, [
          input('Ticker', 'symbol', { maxlength: 32 }),
          select('Interval', 'timeframe', [['1m','1 minute'],['5m','5 minutes'],['15m','15 minutes'],['1h','Hourly'],['1d','Daily']]),
          select('Data mode', 'data_mode', [['historical_bars','Historical bars · fixed vintage'],['recorded','Recorded availability · 1m']]),
          input('Start UTC', 'start', { type: 'datetime-local', step: 1 }), input('End UTC (exclusive)', 'end', { type: 'datetime-local', step: 1 }),
          input('Fast SMA', 'fast_window', { type: 'number', min: 1, max: 9999, step: 1 }),
          input('Slow SMA', 'slow_window', { type: 'number', min: 2, max: 10000, step: 1 }),
          input('Shares per entry', 'quantity', { type: 'number', min: 1, max: 1000000, step: 1 }),
          input('Starting cash ($)', 'starting_cash', { type: 'number', min: .01, max: 1000000000000, step: .01 }),
          h('button', { class: 'replay-button', type: 'submit', disabled: busy.value, 'data-testid': 'backtest-run' }, busy.value ? 'Working…' : 'Run backtest'),
        ]),
        h('p', { class: 'backtest-note' }, 'UTC range includes bar starts from Start up to, excluding, End. A closing decision may occur at End. Only locally saved data is used; empty or oversized ranges return an error. Fast SMA must be shorter than Slow SMA. Maximum 10,000 trading bars.'),
        h('p', { class: 'backtest-note' }, draft.value.data_mode === 'recorded'
          ? 'Recorded availability requires saved 1m revisions and receipt times from that period. A later download alone cannot recreate them.'
          : 'Historical bars use the latest saved versions at the run’s data vintage. They assume open/close availability at candle boundaries and cannot reconstruct original revision knowledge.'),
        error.value ? h('p', { class: 'error', role: 'alert', 'data-testid': 'backtest-error' }, `${error.value}${result.value ? ' The earlier result below is unchanged.' : ''}`) : null,
        notice.value ? h('p', { class: 'backtest-notice', role: 'status', 'data-testid': 'backtest-notice' }, notice.value) : null,
        h('section', { class: 'backtest-saved', 'aria-label': 'Saved backtests' }, [
          h('div', { class: 'backtest-table-heading' }, [h('h3', 'Saved runs'),
            h('button', { class: 'secondary-button', type: 'button', disabled: loadingList.value, onClick: () => list() }, 'Refresh saved runs')]),
          listError.value ? h('p', { class: 'error', role: 'alert' }, listError.value) : null,
          h('div', { class: 'backtest-run-list', 'aria-busy': loadingList.value }, saved.value.map((run) => h('button', {
            key: run.run_id, class: `backtest-saved-run ${result.value?.run_id === run.run_id ? 'is-selected' : ''}`,
            type: 'button', disabled: busy.value, 'data-run-id': run.run_id,
            'aria-pressed': result.value?.run_id === run.run_id, onClick: () => load(run.run_id),
          }, [h('strong', `${run.settings.symbol} · ${run.settings.timeframe} · SMA ${run.settings.fast_window}/${run.settings.slow_window}`),
            h('span', `${utc(run.settings.start)} → ${utc(run.settings.end)}`),
            h('span', `${modeName(run.settings.data_mode)} · Return ${percent(run.summary.return_percent)}`),
            h('small', `${utc(run.created_at)} · ${run.run_id}`)]))),
          !loadingList.value && !saved.value.length ? h('p', 'No saved runs on this page.') : null,
          h('div', { class: 'backtest-pages' }, [
            h('button', { class: 'secondary-button', type: 'button', disabled: loadingList.value || savedOffset.value === 0,
              onClick: () => list(Math.max(0, savedOffset.value - 10)) }, 'Newer runs'),
            h('span', `Page ${savedOffset.value / 10 + 1}`),
            h('button', { class: 'secondary-button', type: 'button', disabled: loadingList.value || saved.value.length < 10,
              onClick: () => list(savedOffset.value + 10) }, 'Older runs'),
          ]),
        ]),
        result.value ? h('article', { class: 'backtest-result', 'data-testid': 'backtest-result', 'aria-label': 'Selected backtest result' }, [
          h('div', { class: 'backtest-heading' }, [h('div', [h('p', { class: 'eyebrow' }, 'SAVED RESULT'),
            h('h2', `${result.value.settings.symbol} · SMA ${result.value.settings.fast_window}/${result.value.settings.slow_window}`),
            h('p', { 'data-testid': 'backtest-result-context' }, `${result.value.settings.timeframe} · ${modeName(result.value.settings.data_mode)} · ${utc(result.value.settings.start)} → ${utc(result.value.settings.end)}`)]),
            h('button', { class: 'secondary-button', type: 'button', disabled: busy.value, onClick: (event) => run(event, true) }, 'Rerun saved dataset')]),
          h('p', { class: 'backtest-note', 'data-testid': 'backtest-run-id' }, result.value.run_id),
          h('dl', { class: 'backtest-metrics' }, [
            metric('Starting cash', money(result.value.summary.initial_cash), 'initial'), metric('Final equity', money(result.value.summary.equity), 'equity'),
            metric('Total P&L', money(result.value.summary.total_pnl), 'pnl'), metric('Return on starting cash', percent(result.value.summary.return_percent), 'return'),
            metric('Cash', money(result.value.summary.cash), 'cash'), metric('Shares held', String(result.value.summary.shares), 'shares'),
            metric('Realized P&L', money(result.value.summary.realized), 'realized'), metric('Unrealized P&L', money(result.value.summary.unrealized), 'unrealized'),
          ]),
          h('p', { 'data-testid': 'backtest-counts' }, `${result.value.summary.fills} fills · ${result.value.summary.pending} pending · ${result.value.summary.rejected} rejected · ${result.value.summary.trading_bars} trading bars · ${result.value.summary.warmup_bars} warm-up bars · Entry size: ${result.value.settings.quantity}`),
          h('figure', { class: 'backtest-equity' }, [h('figcaption', 'Account equity · cash + marked position value (USD)'),
            h('svg', { viewBox: '0 0 920 270', role: 'img', 'aria-label': `Backtest equity curve, starting ${money(result.value.summary.initial_cash)}, ending ${money(result.value.summary.equity)}`,
              'data-testid': 'backtest-equity-chart' }, [
              h('line', { x1: 80, x2: 880, y1: plot.value.baseline, y2: plot.value.baseline, stroke: '#9ca6b5', 'stroke-dasharray': '4 4' }),
              h('path', { d: plot.value.path, fill: 'none', stroke: '#2962ff', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }),
              h('text', { x: 72, y: 32, 'text-anchor': 'end' }, money(plot.value.high)),
              h('text', { x: 72, y: 218, 'text-anchor': 'end' }, money(plot.value.low)),
              h('text', { x: 80, y: 250 }, utc(result.value.settings.start)),
              h('text', { x: 880, y: 250, 'text-anchor': 'end' }, utc(result.value.settings.end)),
            ]),
            h('p', { class: 'backtest-mobile-axis' }, `Scale: ${money(plot.value.low)}–${money(plot.value.high)}. ${utc(result.value.settings.start)} → ${utc(result.value.settings.end)}`),
            h('p', 'Dashed line: starting cash. Values follow saved close marks and fills; gaps mean unavailable valuation. The full equity audit below preserves every event. Open positions are not liquidated at the end.'),
          ]),
          table('orders', 'Orders and fills', ['ID / side / status', 'Shares', 'Submitted UTC', 'Filled UTC', 'Fill price / source', 'Rejection'], result.value.orders,
            (row) => [`${row.order_id} · ${row.action} · ${row.status}`, String(row.quantity ?? '—'), utc(row.submitted_at), utc(row.fill?.execution_time),
              row.fill ? `${money(row.fill.price)} · ${row.fill.source} · ${row.fill.event_id}` : 'Not filled', row.rejection_reason ?? '—']),
          table('decisions', 'Decisions', ['Chart time UTC', 'Decision time UTC', 'Fast / Slow', 'Crossover', 'Action / order', 'Reason'], result.value.decisions,
            (row) => [utc(row.bar_time), utc(row.decision_time), `${row.fast ?? 'Unavailable'} / ${row.slow ?? 'Unavailable'}`, row.signal ?? 'Unavailable',
              `${row.action ?? 'Unavailable'}${row.order_id ? ` / ${row.order_id}` : ''}`, row.reason]),
          table('equity', 'Equity audit', ['Time UTC / event', 'Cash', 'Shares / mark', 'Equity', 'Realized', 'Unrealized'], result.value.equity,
            (row) => [`${utc(row.timestamp)} · ${row.event_id}`, money(row.cash), `${row.shares} / ${money(row.mark_price)}`, money(row.equity), money(row.realized), money(row.unrealized)]),
          h('section', { class: 'backtest-assumptions', 'aria-label': 'Backtest assumptions and limits' }, [
            h('h3', 'What this result establishes'),
            h('p', 'This is the outcome of the specified rules on the saved dataset under the assumptions below. It is not evidence of future profitability or a calibrated probability of success.'),
            h('p', 'Upward crossover while flat submits the configured size; downward crossover while long closes all shares. Other ready decisions hold or wait. Warm-up/unfinished evidence cannot authorize orders. Only one order may be pending. Historical fills use a subsequent open; recorded fills use a later eligible receipt. Fill-time cash/share gates can reject an order.'),
            h('ul', result.value.limitations.map((item) => h('li', item))),
            h('p', `Accounting: ${result.value.final_state.assumptions.cost_basis}; money rounded ${result.value.final_state.assumptions.money_rounding}. Fees $0, added slippage $0. Gaps at the next open can change the execution price.`),
            h('p', { 'data-testid': 'backtest-vintage' }, `Data vintage: ${utc(result.value.settings.frozen_at)} · Engine: ${result.value.engine_version}`),
            provenance.value ? h('div', { 'data-testid': 'backtest-provenance' }, [
              h('p', `Source: ${provenance.value.sources}. ${provenance.value.source ?? ''}`),
              h('p', `Availability: ${provenance.value.availability ?? 'Saved event receipt/revision times'}. ${provenance.value.adjustment_policy ?? ''}`),
            ]) : h('p', { role: 'status' }, provenanceError.value ? `Source metadata unavailable: ${provenanceError.value}. The saved result above remains available; retry by reopening it.` : 'Loading saved source metadata…'),
            h('p', { class: 'backtest-hash', 'data-testid': 'backtest-dataset-hash' }, `Dataset SHA-256: ${result.value.dataset_hash}`),
            h('p', { class: 'backtest-hash', 'data-testid': 'backtest-result-hash' }, `Result SHA-256: ${result.value.result_hash}`),
            h('div', { class: 'backtest-links' }, [
              h('a', { href: `/api/backtests/${encodeURIComponent(result.value.run_id)}`, target: '_blank', rel: 'noreferrer' }, 'Open full saved result (JSON)'),
              h('a', { href: `/api/backtests/${encodeURIComponent(result.value.run_id)}/dataset`, target: '_blank', rel: 'noreferrer' }, 'Inspect frozen source and availability (JSON)'),
            ]),
          ]),
        ]) : h('p', { class: 'backtest-empty' }, 'Run a simulation or open a saved run to inspect its trades and account performance.'),
      ]) : null,
    ])
  },
}
