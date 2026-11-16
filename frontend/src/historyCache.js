// Only recent Live windows belong here; Replay and older pages stay independent.
export const INITIAL_HISTORY_BARS = 500

export function createHistoryCache(fetcher = (...args) => fetch(...args)) {
  const entries = new Map()
  const pending = new Map()
  const controllers = new Set()
  let prefetchTimer = null
  let prefetchGeneration = 0
  const key = (symbol, interval) => `live|${symbol}|${interval}`

  function put(symbol, interval, page) {
    const previous = entries.get(key(symbol, interval))
    if (previous?.stream_id === page.stream_id && ['watermark','daily_watermark','interval_watermark']
      .some(field => (previous?.[field] ?? 0) > (page[field] ?? 0))) return previous
    const tail = page.candles.slice(-INITIAL_HISTORY_BARS)
    const times = new Set(tail.map(c => c.timestamp))
    const bounded = {...page,candles:tail,status:page.status.filter(s => times.has(s.timestamp)),
      next_before:page.candles.length > tail.length ? tail[0].timestamp : page.next_before}
    entries.delete(key(symbol,interval))
    entries.set(key(symbol,interval),bounded)
    if (entries.size>10) entries.delete(entries.keys().next().value)
    return bounded
  }

  async function load(symbol, interval, recent = true) {
    const requestKey = `${key(symbol,interval)}|${recent}`
    if (pending.has(requestKey)) return pending.get(requestKey)
    const controller = new AbortController()
    controllers.add(controller)
    const timeout = setTimeout(() => controller.abort(),15000)
    const request = (async () => {
      const query = new URLSearchParams({symbol,timeframe:interval,limit:String(INITIAL_HISTORY_BARS),recent:String(recent)})
      const response = await fetcher(`/api/history?${query}`,{signal:controller.signal})
      if (!response.ok) throw new Error(`History request failed with status ${response.status}`)
      const page = await response.json()
      if (!Array.isArray(page.candles) || !Array.isArray(page.status)) throw new Error('Invalid candle history response')
      return put(symbol,interval,page)
    })().finally(() => {
      clearTimeout(timeout)
      controllers.delete(controller)
      pending.delete(requestKey)
    })
    pending.set(requestKey,request)
    return request
  }

  function update(symbol, interval, message) {
    const previous = entries.get(key(symbol,interval))
    if (!previous) return
    const candleMap = new Map(previous.candles.map(c => [c.timestamp,c]))
    const statusMap = new Map(previous.status.map(s => [s.timestamp,s]))
    if (message.candle && (!previous.candles.length || message.candle.timestamp>=previous.candles[0].timestamp)) {
      candleMap.set(message.candle.timestamp,message.candle)
      statusMap.set(message.candle.timestamp,message.completion)
    }
    const metadata = Object.fromEntries(['market','history_fetch','source','watermark','daily_watermark','interval_watermark']
      .filter(field => message[field] !== undefined && message[field] !== null).map(field => [field,message[field]]))
    if (message.source_time) metadata.latest_source_time = message.source_time
    put(symbol,interval,{...previous,...metadata,candles:[...candleMap.values()].sort((a,b)=>a.timestamp.localeCompare(b.timestamp)),status:[...statusMap.values()]})
  }

  function cancelPrefetch() {
    prefetchGeneration++
    clearTimeout(prefetchTimer)
  }

  function prefetch(symbol, intervals) {
    cancelPrefetch()
    const generation = prefetchGeneration
    prefetchTimer = setTimeout(async () => {
      // Serial low-priority local reads; a foreground selection is never queued behind them.
      for (const interval of intervals) {
        if (generation !== prefetchGeneration) break
        if (entries.has(key(symbol,interval))) continue
        try { await load(symbol,interval,false) } catch { /* A later selection retries visibly. */ }
      }
    },300)
  }

  return {get:(symbol,interval)=>entries.get(key(symbol,interval)),put,load,update,prefetch,cancelPrefetch,
    dispose() { cancelPrefetch(); for (const controller of controllers) controller.abort() }}
}
