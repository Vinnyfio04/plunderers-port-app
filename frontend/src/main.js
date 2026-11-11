import {
  createApp,
  h,
  onBeforeUnmount,
  onMounted,
  ref,
} from 'vue'
import { createCandleChart } from './chartAdapter.js'
import './style.css'

function formatCandleTimestamp(timestamp) {
  const date = new Date(timestamp)

  return {
    date: new Intl.DateTimeFormat('en-US', {
      dateStyle: 'long',
      timeZone: 'UTC',
    }).format(date),
    time: `${new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'UTC',
    }).format(date)} UTC`,
  }
}

function detailItem(label, value, testId) {
  return h('div', { class: 'detail-item' }, [
    h('dt', label),
    h('dd', { 'data-testid': testId }, String(value)),
  ])
}

createApp({
  setup() {
    const chartContainer = ref(null)
    const candles = ref([])
    const selectedCandle = ref(null)
    const status = ref('Loading one-minute candles…')
    const error = ref('')
    let chartAdapter = null

    const selectCandle = (timestamp) => {
      selectedCandle.value =
        candles.value.find((candle) => candle.timestamp === timestamp) ?? null
    }

    onMounted(async () => {
      try {
        const response = await fetch('/api/history')

        if (!response.ok) {
          throw new Error(`History request failed with status ${response.status}`)
        }

        const history = await response.json()
        if (!Array.isArray(history) || history.length === 0) {
          throw new Error('History response did not contain any candles')
        }

        candles.value = history
        selectedCandle.value = history.find(
          (candle) => candle.timestamp === '2026-11-09T14:31:00Z',
        ) ?? history[0]
        chartAdapter = createCandleChart(
          chartContainer.value,
          history,
          (candle) => {
            selectedCandle.value = candle
          },
        )
        status.value = `${history.length} one-minute candles · UTC`
      } catch (requestError) {
        error.value = requestError.message
        status.value = 'Candle history unavailable'
      }
    })

    onBeforeUnmount(() => {
      chartAdapter?.destroy()
    })

    return () => {
      const selected = selectedCandle.value
      const displayTime = selected
        ? formatCandleTimestamp(selected.timestamp)
        : null

      return h('main', { class: 'market-shell' }, [
        h('header', { class: 'market-header' }, [
          h('div', [
            h('p', { class: 'eyebrow' }, 'Live Market Workplace'),
            h('h1', 'Synthetic one-minute sample'),
            h(
              'p',
              { class: 'lede' },
              'Candlestick prices with trading volume aligned to the same UTC minute.',
            ),
          ]),
          h('p', { class: 'status-chip', 'aria-live': 'polite' }, status.value),
        ]),
        error.value
          ? h('p', { class: 'error', role: 'alert' }, error.value)
          : null,
        h('section', { class: 'chart-panel', 'aria-label': 'Market chart' }, [
          h('div', {
            ref: chartContainer,
            class: 'chart-container',
            'data-testid': 'market-chart',
          }),
        ]),
        h('section', { class: 'inspector', 'aria-labelledby': 'inspector-title' }, [
          h('div', { class: 'inspector-heading' }, [
            h('div', [
              h('p', { class: 'eyebrow' }, 'Crosshair details'),
              h('h2', { id: 'inspector-title' }, 'Inspect a candle'),
            ]),
            h('label', { class: 'minute-picker' }, [
              h('span', 'UTC minute'),
              h(
                'select',
                {
                  'aria-label': 'Inspect candle by UTC minute',
                  value: selected?.timestamp ?? '',
                  onChange: (event) => selectCandle(event.target.value),
                },
                candles.value.map((candle) =>
                  h(
                    'option',
                    { value: candle.timestamp },
                    `${candle.timestamp.slice(11, 16)} UTC`,
                  ),
                ),
              ),
            ]),
          ]),
          selected
            ? h('dl', { class: 'detail-grid', 'data-testid': 'candle-details' }, [
                detailItem('Date', displayTime.date, 'detail-date'),
                detailItem('Time', displayTime.time, 'detail-time'),
                detailItem('Open', selected.open, 'detail-open'),
                detailItem('High', selected.high, 'detail-high'),
                detailItem('Low', selected.low, 'detail-low'),
                detailItem('Close', selected.close, 'detail-close'),
                detailItem('Volume', `${selected.volume} shares`, 'detail-volume'),
              ])
            : h('p', 'Move the crosshair over a candle or choose a minute.'),
        ]),
        h('footer', { class: 'attribution' }, [
          h(
            'p',
            'TradingView Lightweight Charts™ Copyright (с) 2025 TradingView, Inc.',
          ),
          h(
            'a',
            {
              href: 'https://www.tradingview.com/',
              target: '_blank',
              rel: 'noreferrer',
            },
            'Visit TradingView',
          ),
          h(
            'a',
            {
              href: 'https://tradingview.github.io/lightweight-charts/docs',
              target: '_blank',
              rel: 'noreferrer',
            },
            'Lightweight Charts documentation',
          ),
        ]),
      ])
    }
  },
}).mount('#app')
