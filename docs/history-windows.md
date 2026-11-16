# Chart history ranges

Researched November 15, 2026. Popular platforms do not share one professional standard for history depth. TradingView uses subscription bar budgets; thinkorswim offers date ranges. This app combines a bounded chart with the history its existing Yahoo integration can actually supply. No new vendor, subscription, package or key is required.

## Primary sources

- [TradingView: historical intraday bars and limits](https://www.tradingview.com/support/solutions/43000480679-historical-intraday-data-bars-and-limits-explained/) lists 5,000 intraday bars for the basic tier, then larger paid limits up to 40,000. Daily history is not subject to those intraday limits. The app uses 5,000 as a practical browser working budget, not as a claim of equivalent provider coverage.
- [Schwab thinkorswim: Time Charts](https://toslc.thinkorswim.com/center/howToTos/thinkManual/charts/Chart-Aggregation/Time-Charts) describes intraday date ranges through 360 days and a Max daily range. Available combinations depend on aggregation. That establishes a useful longer intraday precedent, but does not increase Yahoo's retention.
- [Interactive Brokers: historical bars](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars) distinguishes request duration and bar-size constraints. Such request limits do not guarantee total available history for every instrument or account; they are not used as a Yahoo coverage promise.
- [yfinance history implementation](https://raw.githubusercontent.com/ranaroussi/yfinance/main/yfinance/scrapers/history.py) uses an 8-day maximum request for 1-minute history, 60 days for 5/15-minute data and 730 days for hourly data. The installed yfinance 1.8.0 source was also inspected and has these branches. Provider behavior can change; failed requests keep cached data and display availability errors.

## Selected ranges

- **1 minute: 7 calendar days.** Useful for recent session detail; avoids a large minute chart and leaves headroom under Yahoo's short retention. Around five full regular sessions normally fit under the chart budget.
- **5 minutes: 60 calendar days.** Provides several weeks of intraday structure within Yahoo's fine-resolution limit.
- **15 minutes: 60 calendar days.** Same source horizon with fewer bars and broader session context.
- **Hourly: 730 calendar days, about two years.** Makes use of Yahoo's longer hourly retention for multi-month context. Regular-session hourly bars are aligned to the session open; the last bar may cover only 30 minutes or be shorter on an early close.
- **Daily: maximum available provider history.** The earliest date is read from saved Yahoo results, never assumed from a listing date.

These are practical product choices informed by the sources, not a surveyed consensus of professional traders. Calendar-day windows contain only actual regular-session bars. Holidays and overnight gaps are not filled. A one-minute safety margin is applied at the provider retention boundary. The source can return less history than requested.

## Storage, retrieval and live continuity

Native 5m/15m/1h downloads are stored in typed `interval_candles`, keyed by instrument, interval and UTC start. Changed values append to `interval_revisions`; identical downloads add no revision. Fetch status and availability times are recorded in `interval_history_fetches`. Schema migration 4 is additive in `backend/data/market.db`; existing observations, Daily history, account IDs and recovery copies are retained.

On first selection the matching provider interval is downloaded in the background for its window. Subsequent recent successful downloads fetch an overlapping tail instead of the full range. Concurrent selections share one task per symbol/interval. Open-session reconciliation runs at most once per minute for displayed intervals; a cache through the most recent completed session can be reused for 24 hours when closed, with a 60-second retry throttle. History responses never wait for the provider. Initial chart windows and serial prefetch use at most 500 bars; prefetch reads local data only. An empty local result displays loading while background work finishes. Network waits remain outside the serialized database writer.

If an hourly request returns no bars, the downloader makes at most one fallback using Yahoo's supported `60m` spelling, with the start inside 729 days (or the narrower incremental overlap). The normal request still targets 730 days; the fallback can return slightly less at that boundary. Each request has a 10-second timeout, there is no retry loop, and successful primary responses need no fallback. Both paths retain `1h` as the application interval and use identical session/OHLCV validation and revision storage. Empty/invalid results and request failures now have useful safe messages; a failed refresh never erases saved candles.

The response merges matching provider bars with existing minute aggregation by timestamp. Fully covered minute aggregates win; completed provider bars supply missing/partial historical coverage. Forming intervals use observed minutes. No provider bar is expanded into fabricated minute ticks, and source volumes are replaced rather than added. Provider `coverage_complete` describes a reported completed interval; `available_minutes=null`, `source_resolution` and `coverage_basis` distinguish it from a complete local minute capture. Missing volume remains null, not zero.

HTTP pages remain at most 2,000 bars. The normal chart applies the selected time horizon, exposes `history_policy` and `history_earliest`, and offers Earliest/Latest navigation. Native revision cursors update WebSocket clients; a large backfill triggers a bounded history resnapshot. The Vue working set is at most 5,000 intraday bars or 6,000 daily bars. Database records outside the browsing horizon are not deleted. Replay continues to use original receipt order, and as-of history excludes versions fetched after its cutoff. Explicit fixture/offline modes do not download history.

## Verification status

Research and source review are complete. No tests, builds, compile checks, endpoint assertions or browser checks were run, following the student's continuing instruction. Actual returned ranges, provider hourly alignment, migration on startup, Earliest navigation, revised-bar precedence and socket updates remain unverified for this change. See `verification.md` for activation observations and pending checks.
