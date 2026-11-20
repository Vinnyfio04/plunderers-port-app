# Archived handoff — before step 7

Saved November 19, 2026 before final reconciliation. This is historical context; use [current.md](current.md) for the authoritative handoff. The body below preserves the preceding handoff and its dated snapshots.

# Plunderer's Port — current handoff

Updated November 19, 2026 (America/New_York). Current stage is below; older snapshots are retained for context. Detailed historical checks, failures and corrections remain in [verification.md](../docs/verification.md).

### November 19 — approved step 6

Step 6 is complete locally. `node scripts/check-project.mjs` runs the same 11 check groups used by the revised GitHub Actions workflow: pip integrity, SMA reference, accounting, causal backtests, SDK memory, frontend policy/build, complete browser SmokeTest, and focused strategy/chat/comparison browsers. All passed on the first complete run (about seven minutes); 24 Python unit tests and seven frontend tests passed, with all retained browser scenarios. Added UI checks prove no duplicate saved run after a lost response, exact audit pagination, and complete saved-result/ID preservation across a real backend restart. A separate expected missing-interpreter injection correctly returned exit 1 and recorded unrun checks. No production code/database or dependency change, no service restart needed.

The workflow triggers on pushes, pull requests and manual dispatch, uses existing manifests with Python 3.13/Node 24 on Windows, and retains logs plus fixture evidence for seven days. Local runner logs and generated evidence are ignored under `backend/data/check-runs/`; compact review evidence is saved in `docs/evidence/ci-step6-local-1795105633066/`. Local Windows/Python 3.13.17/Node 25.7 passed; hosted Node 24 execution and artifact upload remain unverified because no unreviewed commit/push/dispatch was made. Preserve all earlier student work. Stop here: step 7's final documentation/handoff requires the student's next approval. Required step-6 prompt/verification/current-status notes are recorded; the final documentation stage is not started.

### Historical November 19 — approved step 5

The Backtesting performance workspace is implemented in `frontend/src/BacktestPanel.js`, opened from the toolbar. It configures runs, browses/reopens saved results, reruns frozen datasets, displays equity/P&L/cash/positions, paginated orders/decisions/equity events, and data/execution assumptions. Its draft and saved result remain independent of the current market chart and live paper account. Existing dependencies/API/schema are reused. Focused real-browser checks and the production frontend build pass. Known constructed $1,040/$40/two-fill result agrees across UI/API/SQLite; pending/rejected orders, errors, reload/rerun, delayed responses/chart isolation and mobile are checked. A read-only actual cached AAPL inspection confirms $999.32 equity, -$0.68 P&L, 23 fills and both audit pagination paths; screenshots/observed JSON are in `docs/evidence/backtest-workspace-1795104683196/`.

Step-5 full regression exposed the previously recorded host-clock-dependent closed-market assertion, then an unordered HTTP fixture delivery (.099 before .098). The fixture clock and single-connection FIFO transport were corrected without changing production logic or weakening assertions. Final complete `node scripts/smoke-test.mjs` PASS (stream p95 244 ms; existing $1,025/zero-share/$25-realized accounting intact); full results/failures are in verification.md. The historical step-4 notes below describe the earlier approval boundary. No commit/push or step-5 dependency/migration/CI change; no backend restart required. Stop after step 5: broader browser/CI work in step 6 requires the student's next approval.

### Historical November 18 addendum — workplace-chatbot (step 4 boundary)

Next-stage plan is gated one step at a time. Steps 1–4 were implemented at this snapshot: explicit SMA pair/quantity preview, shared/reference-verified SMA engine, shared integer-cent accounting and isolated SimulationAccount, and the causal historical backtest runner/API with immutable datasets and saved results. Version 5 adds backtest-only tables through the central migration path. Fixed-vintage historical bars and strict recorded-availability 1m mode are distinguished explicitly; no provider/model call or live paper order is made by a backtest. Completed runs/settings/data/trades/decisions/equity persist; in-flight jobs do not resume after restart. Eight backtest/API/causality/persistence tests, eight accounting tests and the full offline browser SmokeTest passed. A real HTTP cached AAPL run (November 13, SMA 5/20) and rerun produced matching dataset/result hashes. Production account/decision table fingerprints matched before/after migration and those two saved backtests; foreign keys were clean. Backend restarted as PID 25824 on 8000, frontend on 5173; both HTTP 200. No step-4 dependency/manifest/CI change or commit. The then-pending step 5 approval was supplied afterward; see the current stage above.

Conversation comparison is now implemented (prompt 49): backend memory supplies the earlier full tool result and chart time per conversation/ticker/Live-Replay mode; New chat isolates subsequent turns. Focused SDK isolation and real-browser exact-question checks pass. In the final constructed UI run, AAPL/live wait/82% at 14:32 was compared with buy/91% at 14:33, both times appeared in chat, and chart preview/decision changed to the new result. New chat reported no earlier assessment. Screenshots and tool records are in `docs/evidence/chat-comparison-1795016690047/`; verification.md records the first CSV-refresh harness failure, corrected passes, source-label limitation, and the broad suite's same clock-dependent closed-market failure. No authenticated model call was made. Memory limits/restart behavior are documented; no dependency or database change.

Current branch is `workplace-chatbot`, created at the student's request. OpenAI 3.52.0 / Agents 0.24.0 are installed/pinned in the existing Python 3.13 environment; imports and pip check pass. New Assistant Chat calls `/api/chat` and the backend SDK agent's rules/assessment tools; chart capture and existing decision pipeline are shared. Clarification, expandable tools, exact-result display, optional probability, and stale-chart guards are implemented. Focused real-browser fixture assertions pass for rules, unclear request, delayed interval response, synchronized AAPL/wait/82% assessment and tool failure with zero trades. See verification.md for test-harness corrections, final cleanup result, and the full SmokeTest's unrelated clock-dependent closed-market assertion failure. Actual authenticated SDK chat remains unverified. Restart backend/reload UI to activate. No commit/push; preserve earlier dirty documentation and the student's report.md. The historical snapshot below describes the pre-chat state.

## Repository and working state

- Project root: `C:\Users\Owner\Desktop\School Work\5 Fall 2026\IST 402 - Vibe Coding\live-market-workplace`.
- Repository: https://github.com/Vinnyfio04/plunderers-port-app ; branch: `ui-rework`.
- HEAD: `3866209f6d28b842db2bc56e262ae2e05f7d578c` — Plunderer's Port branding and treasure-map logo. Earlier functional fixes are in `f103b0c`; extended history is in `eec27a4`.
- These commits were pushed previously with `[skip ci]`; do not infer a fresh GitHub Actions pass. No remote fetch/push was performed for this handoff update.
- Before this documentation task, only `report.md` was modified. Preserve the student's edit. This task also changes this handoff, `docs/verification.md`, and prompt 46; no application source changes or commit.
- Use [AGENTS.md](../AGENTS.md) and [assignment_instructions.md](../docs/assignment_instructions.md) for standing constraints and Part 4.1 acceptance. The handoff is canonically `handoffs/current.md`; do not create a second `handoff/` directory.

## Implemented capabilities

- Vue dashboard with a TradingView-style light layout, left Watchlist/Decision Analysis/Paper Trading panels, Plunderer's Port name and the original treasure-map logo at `frontend/src/assets/treasure-map.png`.
- AAPL live/history integration using Python/yfinance, FastAPI HTTP/WebSockets and Lightweight Charts. Only supported/loadable symbols appear; Replay can use other symbols already recorded locally. There is no general multi-symbol live subscription UI yet.
- One-minute observation aggregation and 5m/15m/hourly/Daily history. Recent complete minute aggregates remain authoritative; older or partially covered intervals can use matching native Yahoo bars. No fabricated minutes or overnight candles. Source, age, session/feed/socket status, completion and unknown volume stay visible/separate from six-field OHLCV.
- XNYS regular sessions, holidays/early closes, UTC session-aligned timestamps, dated `MM/DD/YYYY HH:mm` labels and automatic next-session continuation. Wheel zooms; Shift + wheel pans horizontally.
- Browsing horizons: 1m seven calendar days; 5m/15m sixty; 1h about 730; Daily maximum available provider history. Hourly empty results have one `60m` fallback inside 729 days, then stop. Unavailable sources retain saved candles and report a safe error.
- Initial chart requests 500 bars. Recent Live windows are prefetched serially from SQLite after rendering, without fetching full Yahoo history for inactive intervals. One chart is reused. At most ten recent cache entries hold 500 bars each; older pages remain available within the 5,000 intraday/6,000 Daily working buffers. HTTP/socket revision catch-up avoids a duplicate history snapshot and covers changes committed between the two connections.
- SQLite observations retain identity, raw fields, source time, receipt order, repeats and identifiable revisions. Read-only Replay reconstructs arrivals, including late/revised values, without changing the recorded session.
- Named per-instance indicators/settings persist in SQLite: SMA and rolling price range. EMA is not implemented. Calculations use completed candles and keep warm-up gaps explicit.
- Long-only local paper account, whole-share orders, pending next-eligible-observation fills, zero fees, idempotent request IDs and transactional cash/shares/fill/P&L records. Weighted-average cost, realized/unrealized P&L history, and Start/Stop reviewed paper automation exist. Automation needs Vue chart captures/browser activity; do not promise unattended operation with the dashboard closed. No live brokerage execution.
- Ask about chart freezes at most 200 completed candles, exports the exact chart-only PNG, and stores the immutable snapshot, image and named answers. Separate gpt-6-luna analyst/reviewer calls share the snapshot; Python independently enforces rules. Errors, conflicts and vetoes make decisions ineligible. Manual analysis creates no order. Payload-size guards, bounded waits, stale-chart detection and capture isolation fix the previous 10,000-value provider error.
- Read-only WebRTC voice discussion of a selected saved decision is implemented. Full live microphone/speaker verification is still pending.

## Database and current recorded data

Use the central path/module: `backend/data/market.db`, `backend/database.py`, versioned migrations, one Uvicorn worker and the backend-owned collector/writer. Preserve `backend/data/market-observations.sqlite3` as the legacy recovery copy; never merge/reset stores automatically. Account and decision IDs must be preserved. Use a separate `MARKET_DATABASE` for fixtures. Credentials, databases/sidecars, captures, logs and local smoke artifacts stay ignored.

Read-only inspection on November 17 found:

- Schema version **4**; production store and legacy recovery copy both present.
- Latest materialized minute: **2026-11-16T20:56:00Z**. Latest received AAPL observation: **2026-11-16T20:56:59Z**, backend receipt **2026-11-16T20:57:00.281798Z**.
- Concrete audit starting point: observation **53**, receipt **66**, price **352.1675**, session cumulative `day_volume` **26651046**, `last_size` **55**; no `test_data` flag. These stored fields have not been matched to an original captured WebSocket message and visible chart in this task. Do not treat them as proof that Part 4.1 live evidence is complete.
- Latest saved native fetch audits: 5m `ok`/3276 rows, 15m `ok`/1092 rows, 1h `ok`/3464 rows. These audits are from November 15 local; they are not a claim of fresh November 17 downloads.
- Five saved decision records and zero paper orders. No account mutation or new model request was made for this handoff.

Earlier actual Yahoo HTTP/browser checks found 1,950 minutes for November 9–13 and hourly history from November 18, 2024 through November 13, 2026. Those are dated observations, not current freshness guarantees. The newer November 16 records supersede older claims that the store contains only after-hours data or ends on November 13.

## Verification evidence and limits

See [verification.md](../docs/verification.md) for expected/observed results and provenance. Keep constructed market data, actual Yahoo history and actual model calls clearly distinguished.

- Earlier full offline browser SmokeTest passed with real Chrome/Vue/FastAPI, disposable SQLite, deterministic source/model boundaries, replay/indicator checks and paper buy/sell/close ending at $1,025, zero shares, $25 realized, three fills. Some intermediate/repeat runs failed reconnect/readiness and were corrected; do not generalize older passes to every subsequent change.
- November 15 focused final checks passed: six chart-analysis backend regressions; four recent-cache tests; nonblocking history/cursor backend checks; `--intervals-only` browser checks; `--decisions-only` browser checks; four hourly recovery tests. Older paging, cache updates, same-canvas switching, HTTP/socket catch-up, provider failure/recovery and frozen PNG/SQLite agreement were covered. An added pixel check verified bulk refresh and older indicator values cannot corrupt the capture.
- The **16 ms** cached-switch result was measured in one controlled fixture while foreground HTTP was held. It is not a production latency guarantee.
- A separate real gpt-6-luna analysis on isolated **synthetic market candles** succeeded: analyst wait/downward/sufficient; reviewer reject_unsupported_signal; saved answers/image agreed, and orders/fills stayed zero. A reviewer veto is an expected safety result, not an API transport failure.
- November 15 actual hourly refresh saved 3,464 bars and the browser displayed 500 hourly candles/Earliest 2024-11-18 with the old error gone. The bounded fallback branch was tested separately with constructed empty replies; the real successful fetch did not record which interval spelling succeeded.
- Branding and original-image loading were visually checked in the browser. No functional suite was needed for those cosmetic edits.
- **No tests, builds, provider calls, browser actions or service restarts were run on November 17 for this documentation task.** Only repository/docs and read-only database metadata were inspected. The complete suite has not been rerun on the latest branding commit.

## Current limitations

1. **Highest-priority acceptance gap:** one actual regular-session Yahoo message still needs a documented match through its observation/receipt IDs, minute candle/revision/provenance, FastAPI WebSocket message and visible chart. November 16 records offer an audit starting point, but there is no new complete chain in the verification log. Also demonstrate real upstream-unavailable/stale status independently of the still-connected local socket, with cached history visible.
2. No current November 17 provider/browser/service-readiness claim. Stored latest time is November 16 20:56 UTC; investigate collector continuity/freshness before calling the screen current. Old process IDs and next-open labels in historical notes are stale.
3. Yahoo can return empty/limited history, omit usable volume or revise bars. Cached display and one hourly fallback do not guarantee availability or exact requested depth. Unknown volume must remain unknown until a usable baseline/reconciliation exists. Daily maximum-history Earliest navigation and all provider/calendar edge cases do not have comprehensive focused real-data browser evidence.
4. Live microphone/speaker checks require a person with working hardware and permission. The student previously could not use a microphone. Mocked voice checks do not prove a two-way live conversation or microphone release on the user's browser.
5. Indicators and paper-trading UX remain limited; EMA and broader indicator customization are not implemented. Analysis needs adequate completed history and distinct fast/slow SMAs for an actionable crossover. Additional indicator configurations can still reach provider limits and must get a clear validation error.
6. Decision review is categorical and advisory. Reviewer rejection/insufficient evidence may be correct; distinguish those outcomes from transport/validation failures. The student wants clearer analysis presentation and further narrow-screen/header/paper-account UI refinement.
7. `report.md` is student-edited and currently uncommitted. It still contains the old repository URL, an unfinished voice limitation sentence, and wording that can confuse expected decision rejection with failed feature checks. Review suggested corrections with the student; preserve their wording and do not silently rewrite it during unrelated tasks.

## Run and resume safely

Last documented environment: existing Python 3.13.17 at the executable below, Node 25.7.0/npm 11.10.1, FastAPI 0.162.3, Uvicorn 0.54.0, yfinance 1.8.0, exchange-calendars 4.13.2, Vue 3.5.45, Vite 8.3.7 and Lightweight Charts 5.2.1. Dependency declarations/lockfile were inspected; no installations are needed for a handoff. Do not create a virtual environment by default.

From the project root, use the existing documented commands:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
Set-Location frontend
npm run dev
```

Dashboard: http://127.0.0.1:5173/ ; backend docs: http://127.0.0.1:8000/docs . These are configured URLs, not a liveness assertion. Identify current listeners before starting/stopping services; use Ctrl+C in the owning terminal. The prior restricted-sandbox Vue launch was unreachable from the host; if that recurs, use the approved normal host launch and a single bounded reachability check.

Root `.env` is ignored and present. The backend reads environment variables; its plain startup command does not automatically load that file. Load the existing key privately into the backend process for model/voice features, as README documents. Never display its value, put it in prompts/logs, or assume it survives a restart. Yahoo subscriptions do not require a Yahoo login/API key. Fixture flags/database overrides must not leak into normal startup.

## Recommended next steps

1. **Concrete next task:** audit observation 53/receipt 66 and its November 16 20:56 candle/revisions to establish what was actually recorded, check why the current store ends there, then capture one fresh regular-session observation through SQLite -> backend candle -> WebSocket -> visible chart. Record source/receipt times, price, available volume, completion and source-age status. Use a bounded observation window; mark anything not observed pending. Do not relabel historical HTTP bars or constructed inputs as live evidence.
2. During that same focused session, verify next-minute volume reconciliation and an upstream disconnect while the browser-to-FastAPI socket stays connected. Preserve cached history and distinct unavailable/stale labels.
3. When hardware is available, complete one live voice session and follow-up against a selected saved decision; compare speech with SQLite, end it and verify microphone release. Otherwise retain the explicit pending status.
4. Reconcile the student's report/README acceptance wording with the dated evidence and canonical repository name. Then prioritize decision readability, responsive toolbar and paper-trading usability with the student before adding indicators/symbols.
5. Use only checks relevant to the next change. Available commands: selected Python with `-m backend.check_recent_history`, `-m backend.check_chart_analysis` or `-m backend.check_hourly_history`; `node --test scripts/check-history-cache.mjs`; browser `node scripts/smoke-test.mjs --intervals-only` or `--decisions-only`. The full `node scripts/smoke-test.mjs` includes unrelated scale/automation work; run it only when that broader coverage is justified. Log failures/passes; AutoLoop stops on success, five correction cycles or required permission. No blanket full-suite run is authorized by this documentation request.
6. Show changes for student review before committing. No commit/push or dependency change is requested here.
