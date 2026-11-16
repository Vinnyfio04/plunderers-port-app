# Design pipeline

## Nonblocking interval loading — November 15, 2026

The selected chart initially reads 500 recent bars from SQLite. Yahoo reconciliation is scheduled separately; no history response waits for a provider download. The typed rows and minute/Daily/native revision cursors are read in one SQLite snapshot, avoiding a change between the returned rows and their cursor. History calculation runs outside the async event loop. Empty caches return explicit loading/pending state while background work proceeds; unavailable providers preserve saved candles.

Vue reuses its chart and restores a recent Live cache entry immediately, with its real source age/session/completion and a refreshing notice. After the first response it serially prefetches the other four intervals with `recent=false`, `limit=500`, so prefetch does not initiate Yahoo backfill. Foreground selections are not queued behind the background worker. Identical reads share a promise; entries retain at most 500 bars, at most ten symbol/interval Live keys, and reject older revision cursors from late HTTP replies. Replay never uses this cache. Prefetch stops on context changes/unmount. Older paging retains its independent 2,000-bar pages and browsing budget. Indicators retain backend warm-up calculations but render only at displayed candle times.

The first HTTP response carries a per-backend `stream_id` and three committed cursors. Vue supplies these when subscribing. A matching backend validates the cursors and sends intervening revisions; it does not resend a complete history window. Large catch-up batches, invalid cursors or a backend restart produce a bounded fresh snapshot. This preserves updates committed between HTTP and WebSocket subscription. WebSocket snapshots/revisions update the recent cache even when a user is browsing older bars. Original source fields, six-field candle shape, session handling, unknown volume, recorder and simulator rules remain intact.

Focused checks and measured fixture behavior are recorded in verification.md. No migration, dependency, additional upstream subscription or hidden chart instance is required.

## Intraday history windows — November 15, 2026

The current browsing policy is 7 calendar days at 1m, 60 at 5m/15m, 730 at 1h, and maximum available Daily history. See [history-windows.md](history-windows.md) for platform research and Yahoo constraints. This extends the original minute-only history requirement to show older native provider intervals without inventing minute data. Fully covered local minute aggregates still take precedence and forming intervals use the existing observation path.

```text
Yahoo native 5m/15m/1h history -> validate session/alignment/completion
                             -> serialized writer -> interval_candles
                                                  -> interval_revisions + fetch audit
Yahoo observed quotes -> receipts -> effective 1m candles -----+
                                                              v
                        bounded matching-interval merge by UTC start
                               -> /api/history + /ws/candles
                               -> Vue: Earliest / Latest / range label
```

Migration 4 adds typed current interval rows keyed by instrument/interval/start, append-only revisions with availability timestamps, and indexed fetch audits. Network downloads are shared per symbol/interval; a recent successful cache gets an overlapping tail, rather than repeated full-window downloads. Displayed intervals reconcile every minute during regular sessions, with cached closed-session reuse and throttled retries. All writes use the existing writer and database; no new dependency or account/schema replacement is involved.

History/status retain six-field candles with separate source resolution, provider coverage basis, unknown volume and completion fields. HTTP and the continuous socket apply the browsing horizon; original Replay receipts and stored rows are preserved beyond it. Native revision cursors join the minute/Daily cursors, and large batches cause a bounded resnapshot. Earliest now works across all intervals and still rejects explicit conflicting bounds; intraday browser memory is capped at 5,000 bars. The Daily section below describes the earlier implementation step. The full offline browser SmokeTest passed after this extension; focused matching-resolution provider fetches and Earliest navigation remain pending.

## Maximum Daily history — November 15, 2026

Daily previously covered only the recent sessions present in the minute cache. It now combines bounded minute aggregation with a separate Yahoo daily history cache fetched using `period=max`, `interval=1d`, `prepost=False`, `auto_adjust=False`, and `actions=False`. Historical daily bars are not converted into fake minute observations. This extends the earlier minute-only daily requirement specifically to make older provider history available.

Schema migration 3 adds `daily_candles` (instrument/session-open primary key, typed OHLCV, session close/expected duration, availability time and revision ID), `daily_revisions` (changed versions and their fetch availability), and `daily_history_fetches` (download result/count/error). Exact repeated bars create no revision; changed bars retain prior values. As-of reads exclude versions not fetched by the cutoff. Calendar construction spans the provider's actual history range so old dates are timestamped at their historical session opens, including UTC time changes and early closes.

Only completed provider sessions are imported. A fully covered minute-derived session remains authoritative for recent data and later minute revisions; the forming day stays on the existing live aggregation path. Provider daily bars fill older or incomplete session coverage. Status records identify `source_resolution` and `coverage_basis`; provider coverage does not imply that all constituent minute observations were recorded. Six-field candles and null-versus-zero volume remain unchanged.

Startup/selection coalesce background daily downloads and persist through the existing writer. An up-to-date cache is reused for a day; missing completed sessions can refresh sooner, with a one-minute retry throttle. Both minute and daily revision cursors drive the Daily socket; a large backfill causes a bounded resnapshot. Intraday source, replay receipts, indicators and paper execution logic are preserved.

Daily HTTP responses expose `daily_earliest`, `daily_latest`, `daily_watermark` and the existing earlier-page cursor. `oldest=true` selects the first bounded page and rejects conflicting bounds; the intraday extension above adds the same navigation to the other intervals. Vue's Earliest control shows the date returned by the cache and positions the first candles in view; historical indicator values load for that window. Leftward paging still reaches intervening history without loading every day into browser memory. Explicit CSV/test/offline modes make no new Yahoo requests. The general offline browser regression now passes; the Daily Earliest operation and live daily reconciliation remain specifically unverified.

## Company selection while the market is closed

Live / History selection requests the recent-history route independently of exchange status. `recent=true` enables background reconciliation when appropriate; both empty and populated stores return their indexed local result without waiting for Yahoo. The startup scheduler and selection route share a per-symbol download task, and rapid selections share/throttle attempts for 60 seconds. Explicit fixture/live-off modes and as-of/cursor reads never initiate this download. Failed downloads preserve the cache and their fetch audit. External waits stay outside the SQLite writer.

Vue renders candles and connects the market socket before loading indicator/account/automation panels. It retains the last successful symbol/timeframe response during a retry, times out stalled history requests, and retries with bounded backoff. Empty-state text distinguishes loading/unavailable history from exchange closure. The Vite API proxy uses Node's installed HTTP keep-alive agent because `Connection: close` reproduced upstream resets on this machine. The full-size history regression exercises the response through Vue's URL; small fixtures alone had not detected that failure. Replay range controls wait for their saved selection before Start is enabled.

## Current continuous pipeline — November 14, 2026

This section supersedes the historical descriptions below where they mention browser-owned collection, a CSV default, the old database path, or rebuilding raw history on every timer tick.

```text
Backend startup -> database owner lock -> backup/migrate -> backend/data/market.db
                            |
Exchange calendar -> Yahoo WebSocket (one backend-owned collector)
                            |
                      bounded FIFO writer
                            |
           observations + receipts + dirty minute projection
                            |
Yahoo recent history -> completed/provisional bar versions
                            |
                  effective candles_1m + revisions/provenance
                            |
       bounded indexed history / requested session aggregation
                            |
              HTTP snapshot + committed revision watermark
                            |
          WebSocket changes (250 ms display coalescing)
                            |
              Vue candlesticks / volume / indicators
```

The central `backend/database.py` path is shared by observations, replay, indicators, decisions, voice and the paper account. `MARKET_DATABASE` overrides it for isolated tests. The backup-API migration copies the entire legacy store, preserves its original IDs and tables, validates integrity/counts/foreign keys, retains the source recovery copy and applies versioned schema changes. A process lock rejects another backend using the same database. Run one Uvicorn worker.

`backend/candle_store.py` owns the current projection and its schema. `instruments` maps symbols to integer IDs/calendar/timezone. `candles_1m` has a `(instrument_id, minute_start)` WITHOUT ROWID primary key, typed OHLC prices, nullable integer volume, completion, session, source, revision ID and update milliseconds. `candle_revisions` appends changed OHLCV/completion states with availability milliseconds and indexes for minute/as-of and change-stream queries. `candle_provenance` links each revision to its Yahoo bar or observation IDs. `yahoo_minute_values` provides indexed typed bar versions, while the original bar JSON/fetch audit remains available. `ingestion_state` keeps the last processed receipt/source time and reconciliation watermark. `schema_migrations` records completed upgrades.

Original `observations`/`receipts` are retained with additive instrument IDs and integer receipt milliseconds; indexes support affected source-time ranges, revision links, receipt ordering and availability. A repeat preserves its receipt but creates no new effective candle. A changed distinct message remains independent unless explicit supersession identifies a revision. Source-time ordering determines OHLC; receipt ordering determines when a late/corrected value becomes visible. Only the affected minute and adjacent baseline-dependent minutes are recomputed. Known zero and unknown volume remain distinct. Completed Yahoo bars replace whole minutes; provisional quote overlays retain unknown volume, never added volume.

`backend/write_coordinator.py` serializes accepted market events and fast simulator/configuration writes with bounded queue backpressure. External network/model waits happen outside that queue; their saved results reenter it. Each market receipt/projection is one short transaction, with WAL, busy timeout and synchronous FULL; paper fills retain their existing atomic cash/position/P&L transaction. Changes are published only after commit. The completion timer runs even without browsers and stores actual completion transitions. There is no routine whole-store tick scan.

`CandleHub.start` owns collection for the backend lifetime. Closed sessions wait on the exchange calendar; open-session failures retry with exponential backoff/jitter. Catch-up/history downloads run in the background and save through the writer, overlapping recent minutes instead of fetching five days repeatedly. The browser does not own or stop collection. Market session, source age, upstream status, local socket status and history-fetch errors are independent. Old/out-of-session quotes do not become fresh current-market candles.

The history route bounds output to 2,000 candles and underlying minute work to a bounded window, returning an earlier-page cursor. Larger intervals use the existing session-open aggregation. Initial WebSocket snapshots carry a committed watermark; later messages carry changed candles with their symbol, interval and status alongside the same six fields. Slow-client queues are bounded; overflow triggers reconnect/resnapshot. Vue retries connections with generation guards, retains at most 6,000 candle points and loads older pages on leftward scrolling. Indicator and snapshot context comes from validated backend warm-up windows rather than browser paging. Existing completed history is baselined so reconnect/backfill cannot create historical automation executions.

Both bottom ticks and crosshair use `MM/DD/YYYY HH:mm` UTC. At reopening, the next actual candle follows the previous actual candle in the chart's logical sequence; its real timestamp preserves the overnight/date gap without fabricated whitespace data. The latest-price viewport remains stable during in-place updates. Decision capture temporarily renders the frozen cutoff and restores the original viewport afterward.

Recorded-session replay still uses original receipts in their arrival order and does not write back to the recorded source. Imported bar/revision history is available only after its recorded fetch/receipt availability in as-of reads. The legacy `candle_states` audit remains preserved; the production minute projection now uses typed revision/completion rows.

## Yahoo minute history and live merge

`yahoo_history.fetch_recent -> Yahoo Ticker.history(5d, 1m, prepost=False, auto_adjust=False) -> yahoo_minute_bars -> recorded_history -> aggregate_timeframe -> FastAPI HTTP/WebSocket -> Vue`.

FastAPI fetches on production startup in a worker thread and refreshes every 60 seconds during XNYS regular hours. An explicit CSV fixture, test feed, or disabled live feed skips external fetches. Failed history requests preserve cached bars and create an unavailable fetch record. The dashboard shows history failure and market-session state independently from WebSocket connectivity.

`yahoo_minute_bars` stores `bar_id`, `ticker`, UTC minute `timestamp`, `fetched_at`, request-start `snapshot_at`, six-field `candle_json`, `completed`, and `payload_hash`. Latest bar ID available at the requested cutoff wins per symbol/minute. Unchanged completed bars do not create a new version; changed/reverted bars are retained. Provisional versions retain their own snapshot cutoff. `yahoo_history_fetches` stores `fetch_id`, ticker, fetch time, status, returned bar count, and a safe failure message. Tables initialize additively on backend startup. Raw `observations` and ordered `receipts` retain the original tick audit and power the existing tick-replay path.

Completed fetched bars are authoritative replacements for matching observed minutes. A provisional fetched bar is extended only by quotes whose source times are later than its request-start snapshot; open stays from the bar, highs/lows expand and close follows the last source-ordered quote. Its volume becomes null until a later history fetch reconciles it. Never add Yahoo bar volume and quote-volume differences. New minutes without a bar use the existing observation aggregation. Larger timeframes aggregate the merged one-minute series once. HTTP as-of cutoffs apply both to bar fetch availability and observation receipt availability; a historical fetch today is not injected into yesterday's tick replay.

On subscription, a history snapshot closes the HTTP-to-socket race and baselines existing completed candles for automation. Thereafter changed minutes and completion states use the existing candle-update message. Thirty-second status messages refresh exchange open/closed state and fetch errors even without quotes. Session open/close and next-open values use the installed exchange calendar, including early closes and UTC changes.

## November 14 recorded-live update

Live history now follows `SQLite observations + receipts -> recorded_history -> aggregate_ticker -> aggregate_timeframe -> /api/history -> Vue`. Receipt cutoffs exclude observations and corrections not yet received. `/ws/candles` uses the same history function and sends every changed candle, including older late minutes. A one-second hub task evaluates completion even when no new quote arrives; it runs while live clients are attached and is canceled at shutdown. The explicit `MARKET_CANDLE_FILE` override remains for labeled test fixtures only.

The additive `candle_states` table has `state_id`, `ticker`, `interval`, `timestamp`, `evaluated_at`, `candle_json`, and `completion_json`. A unique constraint on symbol/interval/time and both JSON values avoids duplicate state rows after reconnect. It records emitted states, while original observations and receipts remain the authoritative replay inputs. Replay still reconstructs at original receipt times. A completion row is a retained evaluation, not a claim that late corrections cannot arrive.

Volume requires a cumulative total in the minute and a same-date baseline in the preceding minute. Missing/gapped baselines and resets produce null. Quote `last_size` is not a complete trade tape and is not summed. Live messages missing totals therefore retain unknown volume rather than artificial bars. The browser distinguishes upstream status, socket status, recorded history, and TEST DATA; an empty history no longer blocks subscription. The original descriptions below predate this update where they refer to CSV startup or unpersisted completion.

## Planned data flow

```text
External market-data API
          |
          v
Backend API client ---> normalization / validation ---> market state
                                                      |          |
                                                      |          v
                                                      |   agentic helper
                                                      |   (context + explanation)
                                                      |          |
                                                      v          v
                                               FastAPI routes / WebSocket
                                                          |
                                                          v
                                                   Vue state layer
                                                          |
                                                          v
                                           charts + watchlist + helper UI
                                                          |
                                                          v
                                                user reviews and decides
                                                          |
                                                          v
                                      user request back through FastAPI
```

The user remains the decision-maker. The app has reviewed **paper** automation but no live brokerage execution. Part 4.1 acceptance criteria and the current evidence gap are in [assignment_instructions.md](assignment_instructions.md).

## File and directory responsibilities

- `backend/`: Python domain logic, market-data clients, validation, agent coordination, and FastAPI routes.
- `frontend/`: Vue components, client-side state, user input, charts, and visible error/loading states.
- `docs/`: Design decisions, data-flow notes, verification commands, and observed results.
- `prompts/`: Numbered major prompts that led to project changes.
- `handoffs/`: Instructions and current state for safely ending and resuming work.
- `README.md`: Purpose, prerequisites, setup, and only those run commands that have been tested.
- `AGENTS.md`: Standing workflow, safety, dependency, testing, and review rules.

## Current implementation inventory

As of November 15, 2026, the frontend-to-backend, persistent history, live-update, and offline replay paths exist:

- `backend/main.py` exposes `GET /api/health` through FastAPI.
- `backend/main.py` prepares the central database, starts the backend-owned collector, and serves bounded indexed history through `GET /api/history`. A CSV is used only when `MARKET_CANDLE_FILE` explicitly selects a labeled fixture.
- `backend/yahoo_stream.py` uses yfinance's asynchronous WebSocket client for a bounded, single-ticker live-stream probe and reports connection and receipt status without credentials.
- `backend/yahoo_stream.py` also exposes the shared continuous subscription callback used by the live candle hub.
- When Yahoo supplies a message, `backend/yahoo_stream.py` immediately sends the raw decoded source dictionary and backend UTC receipt time to `backend/market_store.py`.
- `backend/market_store.py` stores canonical observations separately from receipt events in SQLite. Source time supports market ordering; monotonically increasing receipt IDs preserve arrival order for late or repeated messages.
- `backend/candle_store.py` maintains the typed effective one-minute projection and append-only revisions/provenance. Only affected minutes and adjacent volume-baseline minutes are recalculated after a receipt.
- `backend/recorded_history.py` merges effective one-minute candles with versioned Yahoo history, then derives requested intervals using the XNYS session calendar. Typed interval and daily caches extend provider history without manufacturing minute observations.
- `backend/live_candles.py` owns the upstream task for the backend lifetime, records each observation, broadcasts committed candle changes, and sends feed status independently from the local FastAPI socket state.
- `backend/replay_session.py` opens an existing observation database in SQLite read-only mode, selects a symbol and source-time range, and reconstructs candle state in original receipt order using an in-memory recorder plus the existing aggregation layers.
- `backend/indicators.py` owns the extensible indicator registry, common validation/calculation contract, SMA and rolling-range implementations, and SQLite-backed named instances.
- `backend/paper_trading.py` owns the reusable long-only execution function, pending-order logic, idempotent request IDs, paper market-event arrivals, atomic fills, cash, and positions.
- `prompts/data/sample-candles.csv` is a synthetic practice source available only through an explicit fixture configuration. Production startup loads saved candles immediately and reconciles recent Yahoo history in the background.
- Uvicorn serves the backend on `127.0.0.1:8000`.
- Vite serves the Vue frontend on `127.0.0.1:5173`.
- `frontend/vite.config.js` forwards `/api` requests to FastAPI.
- `frontend/src/chartAdapter.js` converts every ISO UTC timestamp to Unix seconds for both series. It updates the current interval in place, appends a later interval, and safely rebuilds sorted data for an older late update. Unknown volume becomes a histogram whitespace point rather than a false zero.
- The Vue page requests `/api/history` for live mode or `/api/replay/selections` for Replay. Replay opens `/ws/replay` with the saved symbol, UTC range, and timeframe, and displays the current source observation time, original receipt time, read-only state, and disconnected upstream status.
- In live/history mode, Vue reads indicator contracts and saved instances from FastAPI. Lightweight Charts draws each instance while the inspector reports its value or warm-up gap at the selected candle.
- The chart and page include the required TradingView attribution logo, notice, and link.
- Backend and frontend dependency declarations and the frontend lockfile exist.

The Yahoo subscription, SQLite recorder, indexed projections, FastAPI candle WebSocket, and Vue live-update adapter exist. Actual Yahoo HTTP history has been matched across SQLite, the running history endpoint, and the visible chart. A real after-hours Yahoo WebSocket observation was stored but correctly did not create a regular-session candle. The end-to-end in-session WebSocket check remains pending. Vue also has a local watchlist of loadable symbols, decision analysis, and paper automation. OpenAI decision and voice integrations exist; the independent live-voice hardware check remains pending.

## Market-data SQLite schema

The default ignored store is `backend/data/market.db`. `MARKET_DATABASE` selects a separate fixture store. `backend/database.py` copies the legacy `market-observations.sqlite3` with SQLite's backup API only when the new store is absent, preserves the legacy recovery copy and all IDs, rejects unrelated stores, validates integrity/foreign keys, and applies idempotent migrations through the shared recorder. Use one Uvicorn worker so one backend process owns the database and collector.

| Tables | Main fields and purpose |
| --- | --- |
| `observations`, `receipts` | Canonical source payload/hash and source time stay separate from every ordered backend receipt. Exact repeats reuse an observation but append a receipt; explicit supersession retains both versions. Integer instrument/receipt columns and indexes support affected-minute updates and receipt-ordered replay. |
| `instruments`, `ingestion_state` | Stable symbol/calendar identity and the last processed receipt/source/reconciliation watermark. |
| `candles_1m` | Current typed OHLCV projection keyed by `(instrument_id, minute_start)`, with nullable volume, completion, session, source, revision ID, and update time. |
| `candle_revisions`, `candle_provenance` | Append-only changed states with availability time plus the bar or observation IDs that produced each revision. These support as-of reads and change-stream watermarks. |
| `yahoo_minute_bars`, `yahoo_minute_values`, `yahoo_history_fetches` | Raw/versioned recent Yahoo minute history, typed values used by the projection, and safe `ok`/`unavailable` fetch audits. |
| `daily_candles`, `daily_revisions`, `daily_history_fetches` | Typed current and append-only maximum-range daily provider history with fetch availability. |
| `interval_candles`, `interval_revisions`, `interval_history_fetches` | Migration-4 typed provider caches and revisions for practical `5m`, `15m`, and `1h` history windows. |
| `candle_states` | Preserved legacy audit of emitted six-field candle and completion JSON. The production projection uses typed candle revision/completion rows. |
| `schema_migrations` | Applied schema versions and UTC application times. |

Replay opens the recorded source read-only, orders receipts by `receipt_id`, and reconstructs observation-time candles without writing back. A changed state becomes visible only after its receipt or provider-fetch availability. Current candle completion is persisted in typed projection/revision rows and can still change after a late correction.

## Live candle and unavailable-feed message flow

```text
Yahoo AsyncWebSocket dictionary
          |
          v
MarketRecorder.record_message  ---> observations + ordered receipt audit
          |
          +--> record_effect ---> candle revision + provenance + candles_1m
                                      |
                                      v
recorded_history / session aggregation ---> selected 1m / 5m / 15m / 1h / 1d
                                      |
                                      v
CandleHub committed change ---> FastAPI /ws/candles ---> Vue sorted upsert
                                                           |
                                                           v
                                             candlestick + volume series

Yahoo exception/disconnect ---> feed_status=disconnected/stale
          |                             |
          |                             v
          +--> retry/backoff      WebSocket status message
                                        |
                                        v
                           cached chart remains; FastAPI socket stays open
```

Feed messages distinguish Yahoo connectivity from the local FastAPI WebSocket. A failed history download appends an `unavailable` fetch audit and keeps cached candles. An observation outside the XNYS regular session is stored and updates source age/status, but is not turned into a regular-session candle. The deterministic disconnect evidence uses labeled TEST DATA; an actual regular-session Yahoo observation through this complete path is still pending.

## Recorded-session replay flow

```text
SQLite observations + receipts (read-only)
          |
          v
ORDER BY receipt_id                ---> preserve original arrival point
          |
          v
in-memory MarketRecorder           ---> never changes recorded session
          |
          v
aggregate_ticker + aggregate_timeframe
          |
          v
FastAPI /ws/replay                 ---> candle updates + source/receipt time
          |
          v
Vue Replay upsert                  ---> late/revised value appears on original candle
```

The range filters by preserved source time but playback ordering uses backend receipt order. Exact repeats remain visible in the audit sequence without creating another effective observation. A revision is linked to its superseded observation in the in-memory reconstruction, so the earlier stored value remains in SQLite while the replayed candle adopts the correction at its original arrival point.

## Indicator extension flow

```text
completed candles + validated instance settings
          |
          v
Python INDICATOR_TYPES registry
     |                     |
     v                     v
SMA(close)          price range(high, low)
     |                     |
     +----------+----------+
                v
 timestamp + numeric value / null warm-up gap
                |
                v
FastAPI /api/indicators ---> Vue chart line + selected-candle value

Vue create form ---> POST /api/indicators ---> SQLite indicator_instances
```

Adding another calculation requires registering its metadata and window function in Python; Vue discovers its label, input fields, units, and setting constraints through `GET /api/indicator-types`. Instances remain independent because every SQLite row has its own type and serialized validated settings.

## Paper execution flow

```text
Vue or future decision agent
          |
          v
execute_paper_action(request_id, action, quantity)
          |
          +-- hold / wait ----------------> no order
          |
          v
pending/rejected paper_orders row
          |
          v
next live / replay / fixture observation arrival
          |
          v
paper_market_events ---> recheck cash + shares
                              |
                              v
                one SQLite transaction
                |       |       |       |
                v       v       v       v
              cash   position  fill   order status
```

The submission marker is a paper market-event ID, not a candle timestamp, so a price already known before submission cannot fill the order. Replay writes only paper execution events and account tables; it does not change the recorded source observations. The fill retains both observation and receipt IDs for traceability.

## Paper P&L flow

```text
fill transaction -----------------------> weighted cost basis / realized P&L
      |                                                   |
      +----------------------+                            |
                             v                            v
completed 1m candle ---> stable event key ---> paper_pnl_history (append-only)
                             |                  | cash / shares / avg cost
                             |                  | realized / unrealized / total
                             |                  ` time / source / event links
                             v
                    repeat event ignored
                             |
                             v
                  GET /api/paper-account ---> Vue P&L table
```

Fill rows use the fill price as their valuation price. Completed-candle rows are added only while the position is open. Their stable key includes symbol, timeframe, candle start, and close in cents: unchanged reprocessing is ignored, while a late revision that changes the close creates a new retained valuation. A partial sale removes the proportional weighted cost basis and preserves the remaining average cost. SQLite's unique `(account_id, symbol, event_key)` constraint keeps reprocessing idempotent while retaining all earlier rows.

## Frozen chart decision flow

Analysis uses at most 200 completed candles ending at the selected cutoff; this is separate from the larger chart browsing buffer. Python keeps the full bounded context needed for indicator warm-up, but only the selected analysis range and its indicator values go into the provider snapshot. Both role payloads are checked locally against the provider JSON evidence limits. This prevents the observed HTTP 400 on a 1,950-candle input.

The adapter renders the snapshot's actual frozen candles rather than rereading mutable chart data after the snapshot request. Quote updates and bulk history refreshes are retained for restoration after PNG export. If the chart was replaced while the snapshot request was pending, analysis stops with a recapture message before calling the provider. Preflight errors use the same visible error path, old preview/result state is cleared on a new request, and client fetches have finite timeouts. The preview remains tied to its original metadata while live updates continue.

```text
selected completed candle
          |
          v
Vue freezes symbol + interval + range + cutoff candles
          |
          +------> POST /api/decision-snapshots
          |              |
          |              +--> SQLite indicators + paper position
          |              +--> Python fast/slow SMA crossover
          |              `--> immutable decision snapshot
          |
          v
Lightweight Charts takeScreenshot(true) --> chart-only PNG preview
          |
          v
POST /api/decisions (PNG data URL + snapshot ID)
          |
          +--> reject unreadable PNG or mismatched snapshot
          |
          v
one provider user message
  input_text + input_image + input_json.data
          |
          v
named action / crossover / evidence answers
          |
          +--> validate names and choices
          +--> compare visual crossover with Python
          v
reviewer call: same image + snapshot + actual analyst answers + Python facts
          |
          v
named verdict --> Python cash/position/strategy rules
          |
          `--> save both roles, verdict, final check, image hash/path
```

The image and JSON refer to the same persisted snapshot. Live chart updates may continue after capture, but cannot change the preview or its cutoff. Missing, unreadable, insufficient, or conflicting answers make the result ineligible for automated execution. This workflow never invokes the paper-account execution function.

## Reviewed paper automation flow

```text
Vue Start (account 1, SMA strategy, symbol, interval, order size)
    |
newly completed candle (socket or history poll)
    |
    v
SQLite claim UNIQUE(account, strategy, symbol, interval, candle)
    |
    +--> already claimed / Stop --> no model call
    |
    v
frozen chart PNG + snapshot --> analyst --> reviewer --> Python final gate
    |                    same image, snapshot and decision ID
    +--> image/analysis failure --------------------> skipped event
    +--> veto or invalid ---------------------------> skipped event
    +--> hold/wait ---------------------------------> no_order event
    `--> approved buy/sell/close --> pending paper order
                                      |
                             next eligible observed price
                                      |
                         SQLite fill transaction rechecks
                         enabled generation, deadline,
                         cash, shares, pending status
                                      |
                         fill + balance + position + P&L
                         carry the decision ID together
```

Stop increments the persistent automation generation and rejects its pending orders. A model reply that returns later cannot submit an order with the old generation. Claims and events remain in SQLite after restart; a repeated candle returns the earlier event. The browser fixture uses a separate disposable account database and a fixed-response provider. The manual chart question calls only the decision route.

## History timeframe rules

- The local sample is assigned to `AAPL` and XNYS regular trading sessions. Requests for other local symbols return `404`.
- The default `1m` response and every larger timeframe derive from the same minute records.
- Intraday intervals are aligned from the session open, not midnight. Daily intervals use the session's UTC open and close; calendar gaps or missing source minutes never move data into another session.
- A later available record with the same minute timestamp is the effective revision. With an `as_of` cutoff, a revision only replaces the earlier minute after the revision becomes available.
- OHLC uses the first open, highest high, lowest low, and last close in timestamp order. Known minute volumes are summed; any unknown input volume makes the result unknown (`null`).
- Coverage compares available source-minute count with the exchange-calendar count for that interval. `coverage_complete`, `interval_ended`, and `volume_known` remain outside the candle.

## One-minute aggregation rules

- Group effective observations into half-open UTC intervals `[minute start, minute start + 60 seconds)`.
- Sort by source timestamp; use observation ID only as a stable tie-breaker when source timestamps are equal.
- Compute open and close from the first and last source-ordered prices and high and low from every effective price in the interval.
- Keep completion state in `minute_status`, not in the candle object. Reaching the minute boundary marks it ended, but does not prevent a later recomputation.
- Recompute when a late observation arrives. Because source time controls order, a late middle observation can change high or low without incorrectly becoming the close.
- Exclude an observation that is explicitly superseded by a correction and use the latest unsuperseded revision. The superseded row remains in SQLite for audit.
- Keep distinct same-time messages when no correction relationship is known.
- Compute volume from the final cumulative session total in the minute minus the last cumulative total before the minute. Return JSON `null` when that baseline or an in-minute total is unavailable, or when a decrease shows that the session total reset.

## Next design decisions

1. Demonstrate an actual Yahoo regular-session observation through its SQLite observation/receipt IDs, effective candle revision/provenance, FastAPI WebSocket message, and visible Vue chart; record source age and completion.
2. Observe the subsequent completed Yahoo minute reconciliation and compare actual corresponding volume, keeping unknown live quote volume explicit when the source omits a usable cumulative total.
3. Repeat the unavailable-feed observation with the real upstream during that session and confirm cached candles remain visible while upstream and local-socket states stay distinct.
4. Decide whether watchlist preferences should persist locally. Obtain approval before any new dependency or manifest change.
