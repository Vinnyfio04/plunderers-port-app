import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
} from 'lightweight-charts'

const UP_COLOR = '#2dd4bf'
const DOWN_COLOR = '#fb7185'

export function toChartTime(timestamp) {
  const milliseconds = Date.parse(timestamp)

  if (Number.isNaN(milliseconds)) {
    throw new Error(`Invalid UTC candle timestamp: ${timestamp}`)
  }

  return Math.floor(milliseconds / 1000)
}

function formatChartTime(time) {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  }).format(new Date(time * 1000))
}

export function createCandleChart(container, candles, onInspect) {
  const chart = createChart(container, {
    autoSize: true,
    height: 500,
    layout: {
      attributionLogo: true,
      background: { type: ColorType.Solid, color: '#111827' },
      textColor: '#94a3b8',
      panes: {
        separatorColor: '#263348',
        separatorHoverColor: '#334155',
      },
    },
    grid: {
      vertLines: { color: '#1e293b' },
      horzLines: { color: '#1e293b' },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: '#64748b', labelBackgroundColor: '#334155' },
      horzLine: { color: '#64748b', labelBackgroundColor: '#334155' },
    },
    localization: {
      timeFormatter: formatChartTime,
    },
    rightPriceScale: {
      borderColor: '#334155',
      scaleMargins: { top: 0.08, bottom: 0.32 },
    },
    timeScale: {
      borderColor: '#334155',
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 1,
      barSpacing: 72,
      minBarSpacing: 18,
    },
  })

  const candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: UP_COLOR,
    downColor: DOWN_COLOR,
    borderUpColor: UP_COLOR,
    borderDownColor: DOWN_COLOR,
    wickUpColor: UP_COLOR,
    wickDownColor: DOWN_COLOR,
    priceLineVisible: false,
  })

  const volumeSeries = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: '',
    lastValueVisible: false,
    priceLineVisible: false,
  })

  volumeSeries.priceScale().applyOptions({
    scaleMargins: { top: 0.78, bottom: 0 },
  })

  const normalizedCandles = candles.map((candle) => ({
    ...candle,
    time: toChartTime(candle.timestamp),
  }))
  const candlesByTime = new Map(
    normalizedCandles.map((candle) => [candle.time, candle]),
  )

  candleSeries.setData(
    normalizedCandles.map(({ time, open, high, low, close }) => ({
      time,
      open,
      high,
      low,
      close,
    })),
  )
  volumeSeries.setData(
    normalizedCandles.map(({ time, open, close, volume }) => ({
      time,
      value: volume,
      color: close >= open ? `${UP_COLOR}99` : `${DOWN_COLOR}99`,
    })),
  )

  const handleCrosshairMove = (parameter) => {
    if (parameter.time === undefined) {
      return
    }

    const candle = candlesByTime.get(parameter.time)
    if (candle) {
      onInspect(candle)
    }
  }

  chart.subscribeCrosshairMove(handleCrosshairMove)
  chart.timeScale().fitContent()

  return {
    destroy() {
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
      chart.remove()
    },
  }
}
