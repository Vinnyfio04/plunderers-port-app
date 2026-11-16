import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
} from 'lightweight-charts'

const UP_COLOR = '#089981'
const DOWN_COLOR = '#f23645'
const INDICATOR_COLORS = ['#2962ff', '#9c27b0', '#e58900', '#00897b', '#e75480']

export function toChartTime(timestamp) {
  const milliseconds = Date.parse(timestamp)

  if (Number.isNaN(milliseconds)) {
    throw new Error(`Invalid UTC candle timestamp: ${timestamp}`)
  }

  return Math.floor(milliseconds / 1000)
}

export function formatChartTime(time) {
  const date = new Date(typeof time === 'number' ? time * 1000 : `${time.year}-${String(time.month).padStart(2,'0')}-${String(time.day).padStart(2,'0')}T00:00:00Z`)
  const pad = (value) => String(value).padStart(2, '0')
  return `${pad(date.getUTCMonth()+1)}/${pad(date.getUTCDate())}/${date.getUTCFullYear()} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
}

export function createCandleChart(container, candles, onInspect, onLoadOlder = () => {}) {
  const chart = createChart(container, {
    autoSize: true,
    height: 500,
    layout: {
      attributionLogo: true,
      background: { type: ColorType.Solid, color: '#ffffff' },
      textColor: '#616a79',
      panes: {
        separatorColor: '#e3e7ec',
        separatorHoverColor: '#cbd2da',
      },
    },
    grid: {
      vertLines: { color: '#edf0f3' },
      horzLines: { color: '#edf0f3' },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: '#959da9', labelBackgroundColor: '#596579' },
      horzLine: { color: '#959da9', labelBackgroundColor: '#596579' },
    },
    localization: {
      timeFormatter: formatChartTime,
    },
    rightPriceScale: {
      borderColor: '#e1e5ea',
      scaleMargins: { top: 0.07, bottom: 0.31 },
    },
    timeScale: {
      tickMarkFormatter: formatChartTime,
      tickMarkMaxCharacterLength: 16,
      borderColor: '#e1e5ea',
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 1,
      barSpacing: 36,
      minBarSpacing: 5,
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
  let indicatorSeries = []
  let indicatorInstances = []
  let isCapturing = false

  const handleChartWheel = (event) => {
    if (!event.shiftKey || event.ctrlKey || event.metaKey) return
    // Capture Shift+wheel before the library interprets it as a zoom gesture.
    event.preventDefault()
    event.stopPropagation()
    if (isCapturing) return
    const timeScale = chart.timeScale()
    const range = timeScale.getVisibleLogicalRange()
    if (!range) return
    // Some browsers translate Shift+wheel into deltaX; others retain deltaY.
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
    const pixelsPerUnit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? timeScale.width() : 1
    const offset = delta * pixelsPerUnit / timeScale.options().barSpacing
    timeScale.setVisibleLogicalRange({ from: range.from + offset, to: range.to + offset })
  }
  container.addEventListener('wheel', handleChartWheel, { capture: true, passive: false })

  const applyCandleData = (ordered) => {
    candleSeries.setData(
      ordered.map(({ time, open, high, low, close }) => ({
        time,
        open,
        high,
        low,
        close,
      })),
    )
    volumeSeries.setData(
      ordered.map(({ time, open, close, volume }) =>
        volume === null
          ? { time }
          : {
              time,
              value: volume,
              color: close >= open ? `${UP_COLOR}99` : `${DOWN_COLOR}99`,
            },
      ),
    )
  }

  const applyIndicatorData = (instances, cutoffTime = null) => {
    const visibleTimes = new Set(candleSeries.data().map(point => point.time))
    for (const series of indicatorSeries) chart.removeSeries(series)
    indicatorSeries = instances.map((instance, index) => {
      const series = chart.addSeries(LineSeries, {
        title: instance.name,
        color: INDICATOR_COLORS[index % INDICATOR_COLORS.length],
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        priceScaleId: 'indicators',
      })
      series.setData(
        instance.values
          .filter((point) => visibleTimes.has(toChartTime(point.timestamp)) && (cutoffTime === null || toChartTime(point.timestamp) <= cutoffTime))
          .map((point) =>
            point.value === null
              ? { time: toChartTime(point.timestamp) }
              : { time: toChartTime(point.timestamp), value: point.value },
          ),
      )
      return series
    })
  }

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
    normalizedCandles.map(({ time, open, close, volume }) =>
      volume === null
        ? { time }
        : {
            time,
            value: volume,
            color: close >= open ? `${UP_COLOR}99` : `${DOWN_COLOR}99`,
          },
    ),
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
  const onRange = (range) => { if (range && range.from < 5 && !isCapturing) onLoadOlder() }
  chart.timeScale().subscribeVisibleLogicalRangeChange(onRange)
  chart.timeScale().fitContent()

  return {
    setCandles(history, preserveView = true) {
      const visible = preserveView === true ? chart.timeScale().getVisibleRange() : null
      candlesByTime.clear()
      for (const candle of history) candlesByTime.set(toChartTime(candle.timestamp), {...candle,time:toChartTime(candle.timestamp)})
      if (isCapturing) return
      applyCandleData([...candlesByTime.values()].sort((a,b) => a.time-b.time))
      if (visible) chart.timeScale().setVisibleRange(visible)
      else if (preserveView === 'latest') chart.timeScale().fitContent()
      else if (!preserveView && history.length) chart.timeScale().setVisibleLogicalRange({from:-2,to:Math.min(120,history.length)})
    },
    setIndicators(instances) {
      indicatorInstances = instances
      if (!isCapturing) applyIndicatorData(indicatorInstances)
    },
    updateCandle(candle) {
      const normalized = {
        ...candle,
        time: toChartTime(candle.timestamp),
      }
      const latestTime = Math.max(...candlesByTime.keys())
      candlesByTime.set(normalized.time, normalized)
      if (isCapturing) return
      if (normalized.time < latestTime) {
        const ordered = [...candlesByTime.values()].sort(
          (left, right) => left.time - right.time,
        )
        candleSeries.setData(
          ordered.map(({ time, open, high, low, close }) => ({
            time,
            open,
            high,
            low,
            close,
          })),
        )
        volumeSeries.setData(
          ordered.map(({ time, open, close, volume }) =>
            volume === null
              ? { time }
              : {
                  time,
                  value: volume,
                  color: close >= open ? `${UP_COLOR}99` : `${DOWN_COLOR}99`,
                },
          ),
        )
        return
      }
      candleSeries.update({
        time: normalized.time,
        open: normalized.open,
        high: normalized.high,
        low: normalized.low,
        close: normalized.close,
      })
      volumeSeries.update(
        normalized.volume === null
          ? { time: normalized.time }
          : {
              time: normalized.time,
              value: normalized.volume,
              color:
                normalized.close >= normalized.open
                  ? `${UP_COLOR}99`
                  : `${DOWN_COLOR}99`,
            },
      )
    },
    async captureThrough(cutoffTimestamp, frozenIndicators, snapshotCandles) {
      const originalRange = chart.timeScale().getVisibleRange()
      const cutoffTime = toChartTime(cutoffTimestamp)
      const frozenCandles = (snapshotCandles ?? [...candlesByTime.values()])
        .map((candle) => ({ ...candle, time: toChartTime(candle.timestamp) }))
        .filter((candle) => candle.time <= cutoffTime)
        .sort((left, right) => left.time - right.time)
      if (!frozenCandles.length || frozenCandles.at(-1).time !== cutoffTime) {
        throw new Error('The selected cutoff is not available in the chart; recapture it.')
      }
      isCapturing = true
      try {
        applyCandleData(frozenCandles)
        applyIndicatorData(frozenIndicators, cutoffTime)
        chart.timeScale().fitContent()
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        return chart.takeScreenshot(true).toDataURL('image/png')
      } finally {
        isCapturing = false
        const currentCandles = [...candlesByTime.values()].sort(
          (left, right) => left.time - right.time,
        )
        applyCandleData(currentCandles)
        applyIndicatorData(indicatorInstances)
        if (originalRange) chart.timeScale().setVisibleRange(originalRange)
      }
    },
    destroy() {
      container.removeEventListener('wheel', handleChartWheel, true)
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange)
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
      chart.remove()
    },
  }
}
