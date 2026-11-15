# Current project state

**Updated:** November 14, 2026

## Latest handoff — continuous market and market.db

This section supersedes older database-path/lifecycle statements below. On branch `ui-rework`, implemented prompt 24 and the continuous-market plan. Added `backend/database.py`, `candle_store.py`, `write_coordinator.py`, `check_continuous.py`, `continuous_fixture.py` and prompt 24; preserved prompt 23 and its plan. Changed recorder/importer/indexed history, backend-owned collector/reconciliation, FastAPI writer/snapshot context, Vue dated axis/paging/reconnect, SmokeTest, ignores, README, AGENTS, design/assignment/verification docs. No package/lockfile change or commit.

The normal store is now `backend/data/market.db`, migrated by `python -m backend.database` using the installed Python 3.13 executable. All 16 original tables matched their original values before ingestion resumed. Legacy `market-observations.sqlite3` remains as a recovery copy. Schema versions 1/2, integrity and foreign-key checks passed. All consumers use the central path; use one Uvicorn worker, and separate `MARKET_DATABASE` overrides for fixtures. Do not combine recovery and current stores automatically.

`node scripts/smoke-test.mjs` passed twice with real Chrome, Vue and FastAPI, isolated SQLite and stubbed Yahoo/model boundaries. New coverage includes migration/ownership/recovery, recording without tabs, indexed one-million-candle scale, Friday/Monday continuation, dated desktop/mobile canvas labels, in-place/repeat updates and backend restart/reconnect. Second run history p95 110.926 ms, queued writes p95 192.808 ms and commit-to-visible p95 189 ms. Existing replay SMA 10.5, actual PNG payload, visible provider error and reviewed simulator sequence all passed: cash $1,025, shares 0, realized $25/unrealized $0, fills exactly 3. Four AutoLoop corrections and failure evidence are recorded in `docs/verification.md`. Focused Yahoo history, recorded history and timeframe checks, year-boundary formatter, frontend build, Python compile and whitespace checks passed. Test child services/browser and successful databases were cleaned up.

Normal services remain running at `http://127.0.0.1:8000` and `http://127.0.0.1:5173/`; stop each with Ctrl+C in its owning terminal. Health/page return HTTP 200. The actual database/API/browser agree on 1,950 AAPL minutes through Friday November 13 20:59 UTC, close 356.3999938964844 and volume 725503; Market closed, next open Monday November 16 14:30 UTC. Saturday history reconciliation succeeded. Real stream receipt is not inferred from historical download or deterministic fixture checks.

No pending dependency approval or setup question. Next task: during the next regular session, match one real Yahoo observation/receipt ID to its materialized candle, WebSocket update and visible chart, then verify completed-minute volume reconciliation and upstream-unavailable status. Preserve the separate pending live image-model/voice observations. Before resuming, follow `handoffs/create-handoff.md`: read current docs and verify Git status, files, database/schema and the smallest relevant check. Review the current diff with the student before any commit.

## Current capability

The Vue dashboard supports live candles, recorded-session Replay, persisted named indicators, a local long-only paper account with append-only P&L history, and advisory frozen-chart analysis. A completed-candle snapshot freezes candles, volume, indicators, symbol, interval, range, cutoff, and the SQLite paper position; Vue exports a chart-only PNG and displays the retained preview and named model answers without creating an order.

The decision route now uses separate analyst and reviewer calls against the same snapshot and PNG. It saves both named outputs and model names under one decision ID, then Python applies account and SMA strategy rules. Vue displays the reviewer verdict and supporting cash, price, shares, and crossover facts.

Vue now has Start/Stop paper automation controls. A unique SQLite candle claim runs before automatic chart capture and review. Eligible approved actions create pending simulator orders; the next observed price transaction rechecks age, generation, cash, and shares and links the decision ID to the fill and P&L. Fixture automation uses a separate disposable database.

## Files created or changed

- `backend/main.py`: FastAPI application, health route, CSV loader, and history route.
- `backend/yahoo_stream.py`: bounded single-ticker yfinance WebSocket subscriber and normalized output.
- `backend/market_store.py`: SQLite schema, canonical deduplication, revision links, receipt audit trail, and inspection CLI.
- `backend/check_market_store.py`: repeat, changed-value, and restart-persistence verification using labeled test data.
- `backend/candle_aggregation.py`: effective-observation query consumer, one-minute OHLCV calculation, separate ended state, and CLI.
- `backend/check_candle_aggregation.py`: normal, ended, late, correction, reset, and missing-baseline verification.
- `backend/timeframe_history.py`: exchange-calendar session assignment, replay-aware revision selection, timeframe aggregation, and coverage metadata.
- `backend/check_timeframe_history.py`: sample, gap, session, revision, volume-certainty, DST, and early-close verification.
- `backend/live_candles.py`: shared Yahoo task, record-to-candle aggregation, test replay, and FastAPI WebSocket broadcasting.
- `backend/check_live_candles.py`: stored-row, 1m/5m, next-interval, contract, and disconnect verification.
- `backend/replay_session.py`: read-only saved-session selection and receipt-ordered in-memory reconstruction.
- `backend/check_replay_session.py`: deterministic late-arrival, revision, repeatability, count, and empty-range checks.
- `backend/check_replay_websocket.py`: offline FastAPI WebSocket and repeatability verification.
- `backend/indicators.py`: indicator registry, SMA, rolling price range, validation, calculation, and SQLite instance store.
- `backend/check_indicators.py`: labeled fixture, warm-up, independent settings, validation, and restart-persistence verification.
- `backend/paper_trading.py`: long-only account schema, reusable execution function, idempotency, market events, pending orders, and atomic fills.
- `backend/check_paper_account.py`: $1,000 fixture sequence, retry, rejection, hold/wait, and restart verification.
- `backend/check_pnl_history.py`: five-state P&L, repeated-event, direct-SQLite, and restart verification.
- `backend/decisions.py`: immutable decision snapshots, PNG validation/storage, OpenAI Decisions request construction, named-answer validation, and crossover comparison.
- `backend/decision_provider_double.py`: local Decisions API test double that verifies and records the image and JSON parts.
- `backend/check_decision_snapshot.py`: labeled downward-crossover snapshot fixture and SQLite assertions.
- `backend/check_decision_review.py`: three fixed analyst/reviewer cases and persisted-result assertions.
- `backend/check_paper_automation.py`: disposable approval, retry, next-price fill, veto, Stop, and restart check.
- `backend/data/automation-browser-candles.csv`: labeled three-minute browser trigger fixture.
- `backend/requirements.txt`: exact FastAPI, Uvicorn, yfinance, and exchange-calendars pins.
- `frontend/package.json`: project scripts and direct dependencies.
- `frontend/package-lock.json`: exact frontend dependency graph.
- `frontend/index.html`: Vite entry document.
- `frontend/src/chartAdapter.js`: Lightweight Charts candlestick/volume adapter and UTC time conversion.
- `frontend/src/main.js`: chart page, history request, selector, candle details, and attribution.
- `frontend/src/style.css`: responsive chart and inspector presentation.
- `frontend/vite.config.js`: `/api` proxy to `127.0.0.1:8000`.
- `prompts/02-connect-vue-fastapi.md`: task prompt and approved dependency plan.
- `prompts/03-serve-candle-history.md`: local candle-history task prompt.
- `prompts/04-display-candles-with-lightweight-charts.md`: chart task and approved dependency plan.
- `prompts/05-yahoo-finance-stream.md`: Yahoo stream task and approved dependency plan.
- `prompts/06-record-yahoo-updates-sqlite.md`: SQLite recorder task prompt.
- `prompts/07-aggregate-observations-into-candles.md`: one-minute stored-observation aggregation prompt.
- `prompts/08-history-timeframes.md`: exchange-session history timeframe prompt.
- `prompts/09-live-chart-websocket.md`: live backend-to-Vue candle prompt.
- `prompts/10-recorded-session-replay.md`: offline recorded-session Replay prompt.
- `prompts/11-extensible-indicators.md`: extensible named-indicator task prompt.
- `prompts/12-long-only-paper-account.md`: local long-only paper account prompt.
- `prompts/13-paper-account-pnl-history.md`: weighted-average P&L history prompt.
- `prompts/14-ask-about-chart.md`: frozen chart decision prompt.
- `prompts/15-two-role-decision-review.md`: separate analyst/reviewer calls and Python final gate.
- `prompts/16-reviewed-paper-automation.md`: reviewed decision to paper execution task prompt.
- `README.md`: dependency details plus tested start, stop, and verification commands.
- `docs/design-pipeline.md`: current working frontend-to-backend path.
- `docs/verification.md`: dependency, build, HTTP, failure, recovery, browser, and shutdown results.
- `handoffs/current.md`: this handoff.

## Checks performed

- Verified exact Python and frontend dependency versions.
- Built the Vue application successfully with Vite.
- Verified the direct backend health response: HTTP 200 and expected JSON.
- Verified the frontend proxy response: HTTP 200 and identical JSON.
- Stopped FastAPI and confirmed the frontend proxy returned HTTP 502.
- Restarted FastAPI and confirmed both HTTP 200 responses recovered and matched.
- Opened the Vue page in a browser and confirmed the expected JSON was visible.
- Stopped both services with `Ctrl+C`.
- Verified the supplied CSV schema and rows without adding dependencies.
- Verified `/api/history` returned HTTP 200 and three ordered candle objects.
- Compared all six fields in the 14:31 candle; every value matched the second CSV row.
- Opened the live history endpoint in a browser and confirmed the JSON was visible.
- Installed and resolved `lightweight-charts@5.2.1`; npm reported zero vulnerabilities.
- Built the chart-enabled frontend successfully.
- Visually confirmed separate 14:30, 14:31, and 14:32 candles with aligned volume bars.
- Exercised the candle selector and confirmed the 14:31 close was `101` and volume was `850 shares`.
- Confirmed the TradingView attribution logo, notice, and links were visible.
- Installed and imported `yfinance==1.8.0`; both WebSocket clients are available and `pip check` passes.
- Opened an AAPL Yahoo WebSocket subscription without credentials.
- Confirmed bounded no-message behavior: connection opened, receipt unverified, and corrected command exited in 10.12 seconds for an 8-second receipt timeout.
- Verified one constructed observation, its exact repeat, and a changed same-time payload in a disposable SQLite database.
- Confirmed two unique observation rows, three receipt rows, repeat-safe counting, preserved receipt order, and identical records after reopening from a new backend process.
- Confirmed the constructed 15:00 UTC candle before and after its minute boundary: `100/103/100/101`, volume 11.
- Confirmed a late middle observation recomputes high without changing close, identifiable corrections replace only the derived value, and missing/reset cumulative volume becomes unknown.
- Installed and verified approved `exchange-calendars==4.13.2`; `pip check` passes.
- Confirmed the supplied five-minute candle is `100/105/99/104`, volume 3550, with 3 of 5 minutes and partial daily coverage.
- Confirmed a 14:35 gap starts a new five-minute candle in the same session and the next trading session starts a new daily candle.
- Confirmed all five HTTP timeframe values, replay availability, revision replacement, known-zero/unknown volume distinction, frontend build, and browser candle selection.
- Confirmed live candle messages update the same minute, append the next minute, and use the selected backend timeframe aggregation.
- Confirmed the browser displayed matching 1m and 5m values, daily selection, source age, forming state, and upstream-disconnected while FastAPI remained connected.
- Received and stored one actual AAPL Yahoo message at `2026-11-12T00:55:02Z`; it had no volume and was outside regular hours, so no regular-session candle was created.
- Built the Replay-enabled frontend successfully.
- Verified five labeled test observations replay in receipt order, including a late high and identifiable close/volume revision.
- Verified the final 15:00 candle is `100/103/100/102`, volume 12, in the engine, FastAPI WebSocket, and visible Vue chart.
- Ran the same browser selection twice with identical values and an unchanged SQLite observation count of five.
- Verified the upstream Yahoo feed is disabled/disconnected throughout Replay.
- Verified Range 2 and Range 3 calculate 5 and 6 at the third fixture candle, persist after refresh, and remain intact after a rejected zero window.
- Verified SMA uses the same interface and produces timestamp-aligned warm-up gaps and values.
- Verified browser and SQLite paper-account states at $600/4 shares, $710/3 shares, and $1,025/0 shares.
- Verified one stable request retry produced no duplicate, an empty-position sale was rejected, and exactly three fills survived backend restart.
- Verified the five expected P&L states, single-row event reprocessing, direct SQLite agreement, the visible Vue table, and persistence across a backend restart.
- Verified the browser froze the 14:32 UTC recorded crossover, displayed a chart-only PNG preview, and showed `wait`, `downward`, and `sufficient` from the provider test double.
- Verified the provider received a decodable 1008x660 PNG whose SHA-256 matched SQLite and the saved capture, plus `input_text`, `input_image`, and `input_json` in one user message.
- Verified the visual and Python crossover both reported downward, the paper order count remained zero, and unreadable-image and mismatched-snapshot requests were rejected.
- Completed the authenticated OpenAI image check against the labeled crossover fixture. The real `gpt-6-luna` answers were `wait`, `downward`, and `sufficient`; the browser and SQLite agreed, the saved PNG hash matched, and zero paper orders persisted.
- Verified fixed reviewer acceptance, reviewer rejection, and an unaffordable accepted buy; all three saved rows matched direct SQLite and none created an order.
- Ran a live two-call example: the analyst answered `wait/downward/sufficient`; the reviewer rejected the proposal as unsupported. Browser and SQLite agreed on the ineligible result and zero orders.
- Verified one approved fixed decision submitted twice produced one fill at the next $100 test price: cash $600 and four shares. Veto and Stop paths skipped execution; a claim remained deduplicated after restart.
- In the browser, Start, a newly added completed fixture candle, two mocked model replies, pending order, next-price fill, and Stop all matched direct SQLite. Decision ID linked order, fill, and P&L.

Detailed commands, initial launch failures, corrections, and observed output are in `docs/verification.md`.

## Outstanding questions

- Which market-data API will supply the first feed, and is delayed or simulated data acceptable for development?
- Which instrument should be displayed first?
- Should the first live-history source replace the synthetic CSV entirely or fall back to it when stored coverage is incomplete?
- The Decisions integration targets OpenAI `gpt-6-luna`. The ignored root `.env` now supplies the key to the backend process; keep it out of source, prompts, logs, and Git.
- Should watchlists or preferences persist locally, and is authentication needed initially?
- Git is initialized on `main`, with the GitHub repository configured as `origin`.
- The plain `python` command remains masked by a Windows Store alias; use the explicit Python path in `README.md`.
- An in-session Yahoo payload with volume is still needed to verify Replay against an actual captured regular-session database rather than labeled test data.
- Real Yahoo receiver-to-SQLite persistence is verified, but an in-session message with volume is still needed for the actual stored-record-to-visible-candle comparison.
- The offline decision fixtures set `MARKET_LIVE_FEED=0`, so `/ws/candles` intentionally closes before accepting (Uvicorn logs 403). A forced provider timeout and malformed reply still need an explicit external HTTP regression check.
- Paper automation has been verified with fixed provider replies and disposable test observations. A real Yahoo completed candle and live OpenAI automation run remain unverified; the history polling fallback handled the offline fixture.

## Next task

Enable the live feed and verify one real completed Yahoo candle reaches the chart and produces at most one reviewed paper automation event with a configured provider. Keep a disposable paper account for that check.

## 2026-11-12 voice feature handoff

- Added `backend/voice.py`, `backend/check_voice_session.py`, and `prompts/17-decision-voice-conversation.md`; changed `backend/main.py`, `frontend/src/main.js`, `frontend/src/style.css`, `README.md`, and `docs/verification.md` for read-only GPT-Live voice over WebRTC. No dependency file changed and no commit was made. Existing earlier work remains in the dirty worktree.
- The offline mocked session-contract check passed against ignored `backend/data/automation-browser-final.sqlite3`: analyst buy, reviewer accept, one fill at $100, $600 cash/four shares afterward, with decision/order/fill counts unchanged at 1/1/1. Python compilation, Vue build, the saved-decision HTTP response, and unknown-ID/invalid-offer HTTP errors passed. The in-app browser showed the saved decision and canceled a pending microphone request with the mic off.
- A live voice exchange was not heard. The in-app browser's microphone request stayed pending, desktop Chrome control was denied, and the student cannot use a microphone now. The two spoken questions, same-session follow-up, speaker playback, established-session shutdown, and denied microphone case still need a person with a microphone and speaker. Do not report mocked output as actual spoken output.
- Next task: run the README live voice SmokeTest with microphone hardware, compare both spoken replies and captions with the saved SQLite decision, check End releases the browser microphone, and add the actual observations to `docs/verification.md`. Stop the two local servers with Ctrl+C after that check.

## 2026-11-12 offline browser SmokeTest handoff

- Added the canonical `node scripts/smoke-test.mjs` runner, disposable replay seed and direct SQLite state reader, prompt 18, and `.github/workflows/smoke-test.yml`. Updated Replay to emit completion changes, allowed Replay indicators to use the Python calculation, added indicator window editing and an automation order-size update control, and made Vite's backend target configurable for isolated ports. No dependency manifest or lockfile changed; no commit was made.
- The final runner passed twice from separate fresh $1,000 accounts in real headless Chrome. It checked Replay SMA 10.5, decoded chart pixels and matching snapshot at a stubbed model boundary, visible provider-failure status, buy 4 at $100, sell 1 at $110, reviewer veto, close 3 at $105, duplicate candle, and Stop. Both runs ended at $1,025 cash, zero shares, $25 realized and $0 unrealized P&L, three fills. Successful temporary folders and processes were removed. The first failed run's screenshot/database remain ignored under `backend/data/smoke-runs/` as evidence for the one Replay completion correction.
- The push workflow is configured but has not run on GitHub because this work is uncommitted. The student approved ephemeral CI installation of the project's existing pinned requirements and lockfile packages. Live Yahoo, authenticated image-model, and two-way voice observations are separate and not implied by this offline result.
- Next task: review the working-tree changes, then commit and push if the student wants the push workflow to execute. Check the first GitHub Actions run and record its result in `docs/verification.md`. Repeat voice hardware verification when a microphone is available.

## November 14, 2026 — recorded live streaming handoff

- Default live history now uses SQLite through backend/recorded_history.py; explicit MARKET_CANDLE_FILE retains labeled regression fixtures. Observation and revision availability respects receipt cutoffs.
- CandleHub emits changed historical candles, closes forming candles through a one-second evaluation task, and stores emitted candle/completion states in candle_states. Volume stays unknown when missing totals, resets, or adjacent baselines prevent a valid cumulative difference.
- Added backend/check_recorded_history.py and prompt 20. Focused check, old aggregation/replay checks, WebSocket test feed, Vue build, and offline browser SmokeTest passed. Browser showed test OHLC 100/103/100/101 and volume 11 with upstream disconnected/local socket connected. Actual five-second Yahoo probe opened but received no observation.
- Test services on 8014/5175 were stopped. Normal backend/frontend restarted on 8000/5173 with real Yahoo enabled and default recorded database. Browser showed no regular-session candles and an explicit waiting state; no CSV fallback. No dependencies installed; changes remain uncommitted on ui-rework.
- Next: during a regular session, compare an actual volume-bearing Yahoo observation, SQLite IDs, derived candle, WebSocket and Vue. Review real volume availability before claiming Part 4.1 complete. Detailed results are in docs/verification.md.

## November 14 — Yahoo startup history and reconciliation

- Added backend/yahoo_history.py and backend/check_yahoo_history.py, prompt 22, and modified shared recorded history, hub, FastAPI startup/shutdown, Vue market status, and docs. Default startup downloads real Yahoo 1m history; periodic open-session refresh replaces completed minute OHLCV without double counting. Provisional price overlays keep volume unknown until reconciled. Bar revisions/fetches are stored separately from tick receipts.
- Actual Yahoo returned 1950 bars; API, SQLite and browser agreed on Friday 20:59 UTC close 356.3999938964844 and volume 725503. Backend restart and repeat download retained 1950 versions/minutes. UI showed Market closed, next Monday 14:30 UTC. New reconciliation test, recorded-history regression, full offline browser SmokeTest, build and compilation passed after one Windows connection-cleanup fix.
- Servers remain on localhost 8000 and 5173. Work is uncommitted on ui-rework. Next: verify one actual in-session WebSocket tick, provisional update and later Yahoo completed-minute reconciliation, comparing stored records, socket and browser. Keep live evidence separate from historical HTTP and mocked tests.

## Latest override — testing stopped at student request (November 14)

Read this section before relying on earlier passing-state claims. Prompt 27 requests a test-scope review and prohibits further testing. No test process remained at inventory; normal servers are still Vue 5173 and FastAPI 8000. Do not launch tests or provider calls without a later instruction superseding that restriction.

Closed-market history has one complete offline passing run (company-history-resumed-2.log). Its repeat passed history/decision/paper behavior but failed forced-restart reconnection. The latest handshake/retry and exact socket-status edits are untested; do not claim two passing final runs. Detailed necessary/redundant check review and prior failures are in docs/verification.md. No commit was made.

The live model has recorded authenticated success from November 12, using labeled synthetic AAPL data and gpt-6-luna for both roles: analyst wait/downward/sufficient, reviewer reject_unsupported_signal, zero orders. Current live authentication is unverified: root .env has a key assignment, this terminal lacks the environment variable, and the backend does not auto-load .env. No new model request was made. A later authorized follow-up should first confirm configuration, then use only the smallest relevant check; avoid rerunning the million-row benchmark for UI/provider-fixture corrections.

## Latest model verification — prompt 28

The student subsequently authorized privately loading the existing .env key and ONE live model request, but no full suite. The normal backend was restarted on 8000 with the key inherited privately; Vue remains on 5173. One POST /api/decisions against an isolated copy of the retained synthetic AAPL chart fixture returned HTTP 201 in 2.36 seconds, with real gpt-6-luna analyst wait/downward/sufficient and reviewer reject_unsupported_signal. Saved decision dec_3e08ce3484904313894a9573970f0425 matches SQLite, remains ineligible after reviewer veto, and created zero orders. Temporary 8018 backend was stopped. No other tests were run. Key value was never displayed or written to new files. Reload the existing .env assignment privately on future backend restarts; the latest reconnect edit is still untested. Detailed evidence is in docs/verification.md.

## Commit handoff — November 15, 2026

The student authorized committing/pushing all pending changes to ui-rework, without further tests. Commit scope includes continuous market.db migration/storage, backend-owned collection and session scheduling, bounded history and chart updates, closed-market loading/proxy fixes, readiness/reconnect changes, verification scripts, prompts and documentation. The latest reconnect changes remain untested. No tests/builds/provider calls were run for this commit task, and [skip ci] is used to skip the push workflow. Credentials, databases and local evidence stay ignored. See docs/verification.md for the actual live-model success and the full regression's remaining reconnect limitation.
