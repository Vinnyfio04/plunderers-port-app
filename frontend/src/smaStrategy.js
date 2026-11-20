// Account-action display only; SMA values and crossover signals are Python outputs.
export function evaluateSmaStrategy({ config, instances, signals, cutoff, account }) {
  const unavailable = (reason) => ({ available: false, reason, markers: [], action: null })
  if (!config) return unavailable('Select a fast and slow SMA, then apply the strategy preview.')
  const fast = instances.find((item) => String(item.indicator_id) === String(config.fastId))
  const slow = instances.find((item) => String(item.indicator_id) === String(config.slowId))
  if (fast?.type !== 'sma' || slow?.type !== 'sma') return unavailable('Both selected indicators must be saved SMAs for this chart.')
  if (!(fast.settings.window < slow.settings.window)) return unavailable('Fast SMA length must be smaller than slow SMA length.')
  const quantity = Number(config.quantity)
  if (!Number.isSafeInteger(quantity) || quantity < 1) return unavailable('Order size must be a positive whole number of shares.')
  const matching = signals && String(signals.fast_id) === String(config.fastId) && String(signals.slow_id) === String(config.slowId) && signals.quantity === quantity
  const points = matching ? signals.points : []
  const markers = points.filter((point) => point.available && point.signal !== 'none')
    .map(({ timestamp, signal }) => ({ timestamp, signal }))
  const selected = points.find((point) => point.timestamp === cutoff && point.available)
  const common = { markers, fast: fast.name, slow: slow.name, fastWindow: fast.settings.window, slowWindow: slow.settings.window, quantity }
  if (!selected) return { ...unavailable(signals?.error || 'Waiting for shared Python signals, or this candle has insufficient completed SMA history.'), ...common }
  if (!account || !Number.isSafeInteger(account.cash_cents) || !Number.isSafeInteger(account.shares)) {
    return { ...unavailable('The paper account is loading; no strategy action is available.'), ...common }
  }
  const holding = account.shares > 0
  let action = holding ? 'hold' : 'wait'
  let reason = holding ? 'Keep the existing long position; no additional buying while invested.' : 'Stay flat until an upward crossover.'
  let actionQuantity = 0
  if (selected.signal === 'downward' && holding) {
    action = 'close'
    actionQuantity = account.shares
    reason = 'Downward crossover: close the entire long position.'
  } else if (selected.signal === 'upward' && !holding) {
    // An indicative cash gate only; the existing simulator rechecks at actual fill.
    const estimatedCost = selected.estimated_cost_cents
    if (Number.isSafeInteger(estimatedCost) && estimatedCost > 0 && estimatedCost <= account.cash_cents) {
      action = 'buy'
      actionQuantity = quantity
      reason = 'Upward crossover while flat; cash covers the selected quantity at this candle price.'
    } else reason = 'Upward crossover, but cash does not cover the selected quantity at this candle price.'
  }
  return { ...common, ...selected, available: true, action, actionQuantity, reason, chartTime: cutoff }
}
