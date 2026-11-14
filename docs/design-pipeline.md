# Design pipeline

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

## What exists today

As of November 14, 2026, the frontend-to-backend path and offline replay path exist:

- `backend/main.py` exposes `GET /api/health` through FastAPI.
- `backend/main.py` reads the supplied one-minute CSV with Python's built-in `csv` module and exposes its ordered rows through `GET /api/history`.
- `backend/yahoo_stream.py` uses yfinance's asynchronous WebSocket client for a bounded, single-ticker live-stream probe and reports connection and receipt status without credentials.
- `backend/yahoo_stream.py` also exposes the shared continuous subscription callback used by the live candle hub.
- When Yahoo supplies a message, `backend/yahoo_stream.py` immediately sends the raw decoded source dictionary and backend UTC receipt time to `backend/market_store.py`.
- `backend/market_store.py` stores canonical observations separately from receipt events in SQLite. Source time supports market ordering; monotonically increasing receipt IDs preserve arrival order for late or repeated messages.
- `backend/candle_aggregation.py` derives one-minute OHLCV candles for one ticker from effective stored observations. It orders prices by source time and reports minute-ended state outside the six-field candle.
- `backend/timeframe_history.py` derives `1m`, `5m`, `15m`, `1h`, and `1d` history from the same one-minute source. XNYS session schedules align intervals and supply UTC opens, closes, early closes, holidays, and time changes.
- `backend/live_candles.py` owns one upstream task per active symbol, records each observation, invokes both backend aggregation layers, and broadcasts contextual candle or feed-status messages to FastAPI WebSocket clients.
- `backend/replay_session.py` opens an existing observation database in SQLite read-only mode, selects a symbol and source-time range, and reconstructs candle state in original receipt order using an in-memory recorder plus the existing aggregation layers.
- `backend/indicators.py` owns the extensible indicator registry, common validation/calculation contract, SMA and rolling-range implementations, and SQLite-backed named instances.
- `backend/paper_trading.py` owns the reusable long-only execution function, pending-order logic, idempotent request IDs, paper market-event arrivals, atomic fills, cash, and positions.
- `prompts/data/sample-candles.csv` is a synthetic practice source for `/api/history`. Larger sample timeframes are derived from those one-minute rows. Live-mode startup does not yet backfill from saved observations or Yahoo history.
- Uvicorn serves the backend on `127.0.0.1:8000`.
- Vite serves the Vue frontend on `127.0.0.1:5173`.
- `frontend/vite.config.js` forwards `/api` requests to FastAPI.
- `frontend/src/chartAdapter.js` converts every ISO UTC timestamp to Unix seconds for both series. It updates the current interval in place, appends a later interval, and safely rebuilds sorted data for an older late update. Unknown volume becomes a histogram whitespace point rather than a false zero.
- The Vue page requests `/api/history` for live mode or `/api/replay/selections` for Replay. Replay opens `/ws/replay` with the saved symbol, UTC range, and timeframe, and displays the current source observation time, original receipt time, read-only state, and disconnected upstream status.
- In live/history mode, Vue reads indicator contracts and saved instances from FastAPI. Lightweight Charts draws each instance while the inspector reports its value or warm-up gap at the selected candle.
- The chart and page include the required TradingView attribution logo, notice, and link.
- Backend and frontend dependency declarations and the frontend lockfile exist.

The Yahoo subscription, SQLite recorder, both aggregation layers, FastAPI candle WebSocket, and Vue live-update adapter exist. A real after-hours Yahoo observation was received and stored, but it correctly did not create a regular-session candle. The end-to-end in-session live candle check is still pending. Vue also has a local watchlist of loadable symbols, decision analysis, and paper automation. OpenAI decision and voice integrations exist; the independent live-voice hardware check remains pending.

## Market-observation SQLite schema

`backend/market_store.py` creates two market-data tables in the default ignored database `backend/data/market-observations.sqlite3`:

| Table | Main fields | Meaning |
| --- | --- | --- |
| `observations` | `observation_id` primary key; `ticker`; raw, normalized UTC, epoch-millisecond, and unit-tagged source time; `price`, `day_volume`, `last_size`; `raw_payload_json`, `payload_hash`; `relationship`, `supersedes_observation_id` | One canonical source payload per `(ticker, payload_hash)`. A changed same-time message remains separate unless a trusted caller explicitly links it as a revision. The superseded row is retained. |
| `receipts` | `receipt_id` primary key; `observation_id` foreign key; `backend_receipt_time_utc`; `is_exact_repeat` | One row per arrival, including an exact repeat. `receipt_id` gives stable arrival order even when source times arrive late. |

Indexes support ticker/source-time queries and receipt-order replay. `backend/replay_session.py` opens recorded observations read-only, orders receipts by `receipt_id`, and rebuilds effective candles in memory. `backend/candle_aggregation.py` computes minute completion from the evaluation time; timeframe status travels outside each six-field candle. The market-data schema does not persist candle-completion events separately. The default database was read on November 14 and held 39 AAPL observations with November 13 source times; none had `day_volume` or `last_size`, and none fell inside the November 13 regular-session window. These records do not yet prove a visible real live candle or corresponding live volume.

## Live candle message flow

```text
Yahoo AsyncWebSocket dictionary
          |
          v
MarketRecorder.record_message  ---> observations + ordered receipt audit
          |
          v
aggregate_ticker               ---> effective one-minute OHLCV
          |
          v
aggregate_timeframe            ---> selected 1m / 5m / 15m / 1h / 1d
          |
          v
FastAPI /ws/candles            ---> candle + symbol/interval/source/status
          |
          v
Vue upsert                     ---> replace equal timestamp or append next candle
```

Feed messages distinguish Yahoo connectivity from the local FastAPI WebSocket. An observation outside the XNYS regular session is stored and updates source age/status, but is not turned into a regular-session candle.

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

1. Demonstrate an actual Yahoo regular-session observation through SQLite, backend aggregation, FastAPI WebSocket, and the Vue chart; record source age, completion, and unavailable-feed behavior.
2. Resolve live volume and replace the CSV-only startup view with recorded or otherwise sourced market history, keeping synthetic samples explicitly labeled.
3. Decide whether reconstructed candle-completion state satisfies Part 4.1 or whether completion transitions must be stored in SQLite.
4. Decide whether watchlist preferences should persist locally. Obtain approval before any new dependency or manifest change.
