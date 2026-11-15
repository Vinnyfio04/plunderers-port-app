# Continuous AAPL chart and scalable SQLite storage plan

Prepared November 14, 2026 against branch `ui-rework`, commit `ec1fd1f`.

Implementation completed November 14, 2026. `backend/data/market.db` now exists and contains the migrated store. The sections below retain the original design and acceptance gates; the implementation notes at the end and [verification log](verification.md) distinguish measured results from checks that still need a real open market.

## Intended behavior and working assumptions

- Default symbol AAPL, base candle resolution one minute; retain 5m, 15m, hourly and daily views, indicators, decision snapshots, replay and the paper account.
- Use the exchange's regular trading session, as the project already requires. Continue using the installed XNYS calendar for current AAPL session scheduling. Do not infer sessions from weekdays alone. Keep exchange/calendar identity in instrument metadata so it can be corrected or expanded independently.
- The bottom axis and crosshair show **MM/DD/YYYY HH:mm** for every displayed tick label, for example `11/13/2026 20:59`. Keep UTC, which the existing chart uses, and show `UTC` next to the chart. This avoids a silent timezone change. Label spacing may hide some ticks to prevent overlap; every label that is shown includes its date.
- When closed, keep the last real candles and show **Market closed**, last candle date/time, and the next session open. At reopening, append the first observed opening-minute candle immediately after the previous session's last candle. Its actual UTC timestamp and new date remain intact. Do not insert zero-volume/flat candles or overnight whitespace points to fill closed hours.
- Continuity means automatic collection and recovery **while the backend is running**, with honest stale/disconnected states when Yahoo is unavailable. The machine being asleep or the backend being stopped cannot produce live observations; recovery downloads available missed history and labels it as backfill.

## Original limitations found before implementation

1. `CandleHub.add_client/remove_client` starts the Yahoo subscription for a browser and stops it when the last client leaves. Collection therefore depends on an open page.
2. `_clock` calls `recorded_history` every second per subscriber; this loads source history, rebuilds minute candles and loops through all bars. `aggregate_ticker` repeatedly scans observations for each minute. This work grows with retained history and browser count.
3. `available_bars` selects every available bar version and resolves revisions in Python. The normal history route has no pagination/range limit, and wrapping stored timestamps in `julianday` makes efficient cutoff indexing harder.
4. Yahoo startup fetches five days; every open-market refresh fetches those same five days. This repeats network and database work when only recent minutes changed.
5. Vue does not automatically reconnect its candle socket after a backend interruption. Axis labels use the library default; the configured formatter affects localization/crosshair, not the bottom tick formatter.
6. The current default is `backend/data/market-observations.sqlite3`. `.gitignore` does not yet ignore `.db` files and their sidecars.

## Implementation sequence

### 1. Safely establish `backend/data/market.db`

Use one central path/configuration function shared by the recorder, history importer, replay, indicators, decisions, voice and paper account. Default to the absolute project-root path `backend/data/market.db`; keep `MARKET_DATABASE` for disposable tests.

Before opening the new file, ignore `backend/data/market.db`, `market.db-wal`, `market.db-shm`, journals and migration backups. No credentials or market databases enter Git. Reuse Python's built-in sqlite3 and installed packages.

- If the file is absent and no old store exists, create the parent directory/file through sqlite3 and apply versioned migrations.
- If the old store exists, pause its writer and use SQLite's backup API to create a consistent destination, including committed WAL data. Migrate that destination in a transaction. Preserve all existing observation/receipt IDs, revision links, indicator instances, decision/image references, orders, fills, cash, positions and P&L; do not move only candles and strand other features.
- If `market.db` exists, inspect its schema version and migrate only missing steps. Never overwrite a nonempty destination or combine conflicting stores automatically; report the concrete conflict.
- Check integrity, foreign keys, row counts, known OHLCV values, and account/decision relationships before switching every consumer to the new path. Retain the previous database as a recovery copy. An interrupted migration must roll back or resume idempotently, not appear complete.

Run a single Uvicorn worker for the local app. A process lock must prevent two application instances from starting duplicate collectors/writers against the same database. Additional browser tabs are subscribers to the same backend collector.

### 2. Store compact current candles separately from audit history

Create typed columns for queries and aggregation. JSON remains only where the original external payload must be retained for traceability. Avoid duplicating full candle JSON on every timer tick.

| Table | Key and important columns | Purpose |
| --- | --- | --- |
| `instruments` | integer ID; unique symbol; exchange/calendar; timezone; price convention | Keep repeated symbol/session metadata out of hot rows. |
| Existing `observations` and `receipts`, migrated additively | preserve original IDs and raw payload once; integer UTC source/receipt milliseconds; payload hash; supersession link; receipt order | Replay and audit exact repeats, late messages and identifiable corrections. Preserve the original payload's units. |
| `candles_1m` | primary key `(instrument_id, minute_start)`; typed open/high/low/close; nullable integer shares volume; session ID; ended/coverage/provenance flags; effective revision ID; updated-at milliseconds | One effective candle per instrument/minute, directly serving chart history. Store minute_start as UTC epoch seconds. Benchmark `WITHOUT ROWID` for this small composite-key table. |
| `candle_revisions` | integer revision ID; instrument/minute; OHLCV and flags; known-at milliseconds; source kind and source reference | Preserve actual value/status changes and their availability for as-of reads. Unchanged imports do not append revisions. |
| `yahoo_bar_versions` or migrated existing bar table | preserve bar/version IDs, fetch availability, provisional snapshot cutoff and completion; typed OHLCV | Keep Yahoo's downloaded bars distinguishable from quote-derived candles. Compare hashes before writing. |
| `ingestion_state` and fetch audit | per instrument/source; last processed receipt, last source time, reconciliation watermark; fetch range/result | Resume safely and diagnose gaps or unavailable history. |
| `schema_migrations` | version and completion metadata | Idempotent upgrades and recovery. |

Keep the current market-price representation (`REAL`) to avoid silently changing strategy calculations. Prices remain market data, distinct from the paper simulator's existing cent-based accounting. Nullable volume means unknown; integer zero means known zero. Validate numeric ranges, OHLC consistency, minute alignment and nonnegative volume on ingestion.

Indexes should serve actual access paths:

- `candles_1m` composite primary key covers one symbol's chronological range and latest N bars; do not add a redundant index on the same columns.
- Observations: `(instrument_id, source_time_ms, observation_id)` for an affected minute plus its baseline; receipts: `(instrument_id, receipt_id)` for ordered replay. Add an index on `supersedes_observation_id` for effective-observation lookup.
- Revisions: `(instrument_id, minute_start, known_at_ms, revision_id)` for bounded as-of queries. Use comparable integer columns directly instead of SQL date functions in WHERE clauses.
- Keep unique payload identity and relationship constraints. Check `EXPLAIN QUERY PLAN` for hot queries before adding more indexes; excessive indexes slow every ingestion write.

Use WAL on the local disk, foreign keys, bounded busy timeout, one writer queue, short batched transactions, and `synchronous=FULL` because the same store includes persistent paper-account records. Batch market observations for at most 50–100 ms or a bounded count, and publish only committed changes. Apply backpressure when the queue fills; do not silently discard accepted observations. Preserve atomic paper fills/balances/P&L. Use measured checkpoints, short read transactions and consistent backup API snapshots; avoid unconditional VACUUM or deleting live WAL files.

Route simulator and configuration writes through the same writer ownership model while retaining their existing transaction boundaries and request IDs. Process paper submissions and price receipts in their accepted order; batching must not allow an observation already known at submission to become the next eligible fill.

### 3. Own ingestion for the backend's lifetime

Start one AAPL collector, one reconciliation scheduler and one writer at application startup, independent of connected pages. Shut them down cleanly. Honor live-off/test settings so the offline SmokeTest never needs provider access.

- On startup, show saved candles promptly; perform the Yahoo catch-up request in a background task with an explicit loading/failure state.
- Reuse the existing five-day initial history only for an empty store. On normal operation fetch a short overlapping recent range, plus explicitly detected gaps; respect Yahoo's supported retention window and rate limits. A long downtime beyond Yahoo's available minute history remains an explicit gap.
- Reconnect Yahoo with bounded exponential backoff and jitter. Reset backoff on a healthy subscription; resume from stored watermarks and reconcile the overlap. Preserve source timestamps on repeated/stale quotes.
- Schedule sessions from the exchange calendar, including holidays, early closes and daylight-saving changes. At open, reconnect/resubscribe if needed and start catch-up. While open, reconcile recent completed minutes about every 60 seconds. After close, perform a bounded final reconciliation/retry for the last minute, then reduce history polling until the next open.
- Market state, upstream connection state, history fetch state and freshness remain independent. A connected weekend socket is not labeled a fresh live market.

### 4. Update affected candles instead of rebuilding history

For each committed observation, mark its minute dirty and preserve source-time ordering. An exact repeat adds its receipt audit but changes no effective candle. A normal tick updates the current minute in memory and in `candles_1m`; a late observation or correction recomputes only affected minutes from indexed observations.

A correction can also affect the next minute's volume baseline, and a changed reconciliation bar can affect its containing 5m/15m/hour/day candle. Invalidate those dependents explicitly, including the previous/next boundary baselines where applicable. Never assume that only the observation's own minute can change.

Retain the tested merge rule: completed Yahoo bars replace the whole minute OHLCV; provisional bars extend OHLC with eligible newer source-time quotes and keep volume unknown until reconciliation. Never add downloaded volume to a cumulative-volume delta. Persist only changed candle revisions and completion transitions. A timer closes the active interval even with no new quote; ended does not prohibit later revisions.

Keep all larger intervals derived from effective one-minute candles, grouped by session open and calendar boundaries. Compute only the requested bounded range; add an invalidated aggregate cache only if benchmarks justify it. Preserve the six candle fields, with completion, coverage and source metadata outside them.

### 5. Bound HTTP, WebSocket and browser work

- Default startup history to the most recent 2,000 candles; expose `before`/range and a hard page limit. Return a cursor and fetch earlier pages on leftward scrolling. Larger-timeframe requests must restrict the underlying minute range and use bounded batches or streaming aggregation for large exports.
- Read current history from `candles_1m`, not all raw observations or all revisions. Obtain indicator warm-up from only the required preceding window; keep snapshots and strategy calculations independent of which page the student has scrolled to.
- Use a commit/change sequence in snapshots and socket events. Subscribe with a consistent snapshot watermark, then deliver later changes; if a cursor is too old or a buffer overflows, resnapshot. This prevents the history/socket race and missed updates after reconnect.
- Broadcast only changed candles/status to clients for that symbol/interval. Coalesce intermediate display updates at a bounded cadence (target at most 250 ms), retaining every accepted source message in SQLite. Bound per-client buffers so a slow tab does not stall ingestion.
- Vue retries local WebSocket connections, resnapshots after backend restart, and resubscribes to the selected interval. A generation token cancels stale retries after symbol/mode changes or unmount. Reconnect never auto-starts paper automation or re-executes historical decisions.
- Use in-place series updates for the active/latest candle and sorted bounded replacement for older corrections. Keep the last 2,000 loaded points plus bounded pages in the browser; evict offscreen pages when necessary. Append the next session's first actual candle directly after the prior session's final actual candle, keeping their real timestamps and avoiding a reset of the student's viewport.
- Configure `timeScale.tickMarkFormatter` for the bottom axis and `localization.timeFormatter` for crosshair/tooltips to return `MM/DD/YYYY HH:mm`. Increase maximum label length and spacing as needed; the library may show fewer labels at a zoom level. Verify the date remains visible on narrow displays and in captured decision images.

### 6. Plan capacity, retention and maintenance

At an illustrative 252 full sessions/year, one symbol produces `390 * 252 = 98,280` minute rows/year (early closes reduce this). Ten years is roughly one million effective minute rows per symbol. Raw quotes, receipts and revisions can be much larger and must be sized separately. Do not extrapolate a database size from candles alone.

Retain effective minute history for the long term. Keep the existing raw audit during the initial rollout; introduce archive/retention only as an explicit policy with verified restorable backups. Do not delete records merely to meet a performance test. Track row counts, file/WAL size, fetch failures, queue depth, write latency and query latency. Measure with multiple symbols before expanding beyond AAPL. SQLite remains the initial local engine; reconsider storage only when measured contention or dataset size exceeds agreed targets.

### 7. Verification gates and completion criteria

| Requirement/check | Verification |
| --- | --- |
| New path and existing work preserved | Fresh init creates `backend/data/market.db`; repeat init changes nothing. Migrate a copy of the existing store, compare source IDs/counts, latest OHLCV, decision references and paper balances/fills/P&L. Test interruption and conflicting-destination handling. Run integrity and foreign-key checks. |
| Continuous collection | Run with zero browsers, deliver observations, then open Vue and compare saved/current candles. Interrupt/reconnect both upstream and local socket, repeat a receipt and restart backend; verify no missing/duplicate effective candles and no duplicate paper execution. |
| Closed then next open | Deterministic Friday-close/Monday-open fixture: closed label and next-open date, no artificial weekend bars, first Monday minute directly follows Friday's last bar, with its new real timestamp. Repeat for early close and DST boundaries. |
| Dates distinguish sessions | Browser checks visible axis labels and crosshair for two different days, including a year boundary, at desktop/mobile widths and in a chart capture. Every displayed axis tick includes MM/DD/YYYY and time; UTC is explicit. |
| Candle correctness and volume | Same-minute ticks, next minute, exact repeat, late high, explicit correction, changed baseline, provisional/final Yahoo reconciliation and reversal. Compare exact expected OHLCV with SQL and Vue for 1m/5m/daily. Unknown volume is distinct from zero. |
| Replay/as-of integrity | A later fetched bar or revision cannot appear before its availability. Receipt-order replay and saved indicator/decision configuration continue to pass. |
| Large history | Seed at least one million minute candles plus a representative quote/revision dataset on local disk. Inspect query plans; measure p50/p95 startup-range reads, memory, file size, writer throughput, contention, checkpoint latency, and recovery. Load a second symbol and a second browser. |
| Full regression and actual evidence | Extend `node scripts/smoke-test.mjs` to use the new path in an isolated directory, test open/close/reconnect/dates, and retain existing indicator, capture, decision and paper checks. Separately trace an actual open-market Yahoo observation through receipt, effective candle, socket and browser, then verify its reported volume reconciliation. |

Proposed performance acceptance targets, to be measured rather than claimed: warm 2,000-candle API p95 <=250 ms on the documented local machine; committed-tick-to-browser p95 <=1 second under a deterministic 100-observation/second stress fixture; memory and update-query work bounded by active windows, not total history. The stress rate is a test load, not a Yahoo throughput promise. Adjust implementation if the measured gates fail without weakening correctness tests.

## Plan review: requirement match and efficiency

| Student requirement | Where addressed | Review result |
| --- | --- | --- |
| Continuously mark current market state | Backend-owned collection, session scheduler, retries, delta updates and freshness in steps 3–5 | Covered; provider outages and downtime remain visible. |
| Bottom times include mm/dd/yyyy | Both chart formatters, label sizing and multi-day browser gate in step 5 | Covered; existing crosshair-only formatter is insufficient. |
| Closed label and seamless next-session continuation | Exchange calendar, final reconciliation, no fabricated closed-hour candles, retained chart state | Covered. |
| `backend/data/market.db`, create if absent | Central path, fresh creation, safe migration, ignores and restart checks in step 1 | Covered in implementation plan; not created during planning. |
| Efficient candle creation at large size | Typed effective-minute table, indexed dirty-minute recalculation, bounded queries, one writer and batching | Covered with explicit complexity and benchmark gates. |
| Verify plan is efficient | Source inspection, installed chart API types, SQLite documentation and million-row prototype below | Feasible and justified; production efficiency still requires disk/concurrency measurements. |

The shortest implementation path is to keep FastAPI, Vue, Lightweight Charts, yfinance and sqlite3, then change the central storage/read path before the lifecycle and UI. This avoids maintaining two competing live-history implementations. No new dependency is currently required. Adding every possible aggregate/index, sharding databases early, or replaying all observations every second would add work without evidence of benefit. Full refreshes become explicit catch-up/recovery operations; routine updates touch affected minutes and subscribed windows.

### Evidence gathered while reviewing this plan

- Read the live code, store, aggregation, chart adapter, instructions, requirements and Git status. The working tree was clean before this plan; current store uses JSON bar versions and a `.sqlite3` default. `market.db` is absent.
- Confirmed in installed Lightweight Charts types that `tickMarkFormatter`, `tickMarkMaxCharacterLength` and `timeFormatter` are available. See the [time-scale API](https://tradingview.github.io/lightweight-charts/docs/api/interfaces/TimeScaleOptions).
- A disposable **in-memory prototype**, not application production storage, inserted 1,000,000 typed minute rows with a `(instrument_id, minute_start)` `WITHOUT ROWID` primary key. `EXPLAIN QUERY PLAN` reported `SEARCH candles_1m USING PRIMARY KEY (instrument_id=? AND minute_start<?)` for the latest-2,000 query. Across 25 warm reads: median **2.344 ms**, p95 **4.024 ms**, 2,000 rows returned. SQLite allocated **25,317,376 bytes** for this narrow prototype. These figures exclude audit rows, extra columns/indexes, disk/WAL, network, JSON encoding and browser rendering; they are evidence for the indexed access path, not a production capacity guarantee.
- A composite key can avoid a second B-tree with `WITHOUT ROWID`, but its benefit depends on row shape: benchmark the final schema against an ordinary rowid table before committing the optimization. See [SQLite's guidance](https://www.sqlite.org/withoutrowid.html).
- WAL permits readers and the single writer to progress concurrently on one local host; it does not provide multiple concurrent writers. Keep transactions short and evaluate checkpoint behavior. See [SQLite WAL](https://www.sqlite.org/wal.html). Verify index selection with [the query planner](https://www.sqlite.org/queryplanner.html).

Review conclusion: the plan matches the stated requirements and removes the identified growth-dependent hot paths. It is the recommended implementation for this local application's scope. A claim that it is universally the fastest design would be unsupported; the disk, ingestion and browser gates are required before declaring the implementation efficient at its intended scale.

## Implementation review — November 14, 2026

- Database establishment: implemented by `backend/database.py` and `backend/candle_store.py`. The actual legacy store was backed up into `market.db`; all 16 original tables were compared over their original columns and preserved exactly before collection resumed. Schema versions 1/2, integrity and foreign-key checks passed. Disposable checks cover fresh/idempotent creation, conflict refusal, interrupted-copy recovery and duplicate-owner rejection.
- Continuous ownership: the backend starts the collector, timer and reconciliation independently of tabs. Deterministic checks recorded with no client, removed the last client without stopping collection, crossed Friday/Monday, and restarted the backend while Vue automatically recovered. Normal startup serves the saved 1,950 Yahoo bars immediately. Real Saturday market state is closed, with next open Monday November 16 at 14:30 UTC.
- Indexed projection and bounded UI: current minutes, revisions, provenance, source/receipt indexes, cursor pages, a 6,000-point browser bound, indicator warm-up context, queued writes and committed change watermarks are implemented. Completed imported volume replaces observed volume; missing volume stays unknown. Existing replay/indicator/capture/decision/paper regressions pass.
- Dates: desktop and narrow-browser canvas labels were checked for both November 13 and November 16 with full dates/times. The same exported formatter returns `12/31/2026 20:59` and `01/04/2027 14:30` at a year boundary. Exchange-calendar regressions cover summer/winter UTC opens and the November 27 early close.
- Measured efficiency: the actual on-disk schema with one million minute candles plus 50,000 quote, receipt and revision rows uses the composite primary-key search for latest pages. The first full passing run measured 66.25 ms p95 for the 2,000-candle history function and 74.46 ms p95 for 200 queued writes paced at 100/s. Browser commit-to-screen p95 was 222 ms for 100 events paced at 100/s. These are local scoped measurements, not a prediction for unlimited raw feed retention or many concurrent symbols.
- Deliberate implementation adjustment: each market receipt and projection commits in its own short atomic transaction instead of adding a 50–100 ms raw-ingestion batching delay. The bounded FIFO preserves submission/price order and the measured 100/s load passes; display changes are still coalesced at 250 ms. Retain this simpler transaction boundary until measurements justify batching. No aggregate cache, deletion policy, new storage engine or dependency was introduced.
- Remaining evidence: a real regular-session Yahoo tick-to-SQLite-to-WebSocket-to-chart trace, actual next-open continuation and completed-volume reconciliation still require an open market. The quote-replay workflow remains receipt-based. Long-running memory/WAL growth, simultaneous multiple active symbols/tabs and a rowid-versus-WITHOUT ROWID capacity comparison are further capacity checks; the current results establish the bounded indexed path and stated local latency gates, not universal optimality. The expanded SmokeTest is offline and does not replace live provider or microphone checks.

Commands, expected/observed values and AutoLoop failures are recorded in `docs/verification.md`; normal startup and migration commands are in README.
