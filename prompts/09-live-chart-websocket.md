# Connect the Vue chart to live backend candles

Read `AGENTS.md` and `docs/design-pipeline.md`. Trace the existing Vue chart,
Yahoo Finance subscription, observation recorder, and candle aggregators before
editing. Default the chart to one minute and add selectors for every backend
timeframe through daily.

Use a FastAPI WebSocket to send live backend-aggregated candles to Vue for the
selected symbol and interval. Keep exactly the CSV candle fields and carry
symbol, interval, source, feed status, source age, and completion alongside the
candle. Update equal-interval candles in place and append the next interval.
Display upstream status separately from the browser-to-FastAPI connection.

Verify an actual Yahoo update from stored source through the screen when one is
available. Otherwise mark that check pending and use clearly labeled recorded
test input. Disconnect the upstream while leaving the FastAPI WebSocket open,
verify the visible state, and record all browser observations.
