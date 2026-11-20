# SMA strategy workstation — operation, assumptions and evidence

Updated November 19, 2026. The seven implementation stages are complete locally: strategy selection, shared indicators, shared accounting, historical runner/storage, performance workspace, automated checks/CI configuration, and this documentation/handoff. The implementation is still uncommitted for student review. Hosted GitHub Actions execution remains pending a reviewed push. This status does not close the separate [Part 4.1 live-source acceptance gap](assignment_instructions.md).

## Acceptance and where to inspect it

The requested outcome was a workstation that derives signals and measures simulated trading outcomes.

- **Two SMAs and their crossover:** named fast/slow SMA instances, lines on the price chart, crossover arrows and an inspected-candle action preview. Shared Python calculations feed the chart, preview, frozen assessment and backtester. EMA/MACD/RSI are optional and are not implemented; rolling price range is also available.
- **Simulated trading/accounting:** the shared cent-based ledger tracks orders, fills, cash, positions, cost basis and realized/unrealized P&L. The paper account persists separately from each isolated backtest. Trades, prices, times, rejection reasons and valuation records are inspectable.
- **Historical evaluation:** saved-history backtests process causal decisions/events under the selected availability convention. Settings, frozen inputs, decisions, orders and equity persist with run IDs/content hashes. The Backtesting panel shows resulting trades and account performance, with assumptions and limitations.
- **Verification:** installed pandas is the independent SMA/crossover reference; batch/incremental comparisons include forming candles, revisions and future-data invariance. Known accounting examples and real-browser/SQLite comparisons pass. The retained browser checks and core checks are configured for pushes in [GitHub Actions](../.github/workflows/smoke-test.yml). The hosted run itself has not executed for this uncommitted work.

Detailed dated commands, failures, corrections and provenance are in [verification.md](verification.md). The latest compact local check report is [local-checks.json](evidence/ci-step6-local-1795105633066/local-checks.json).

## Use the workstation

Use the existing Python environment and [tested startup commands](../README.md#setup-and-run-instructions). Run one Uvicorn worker; the backend owns collection and the central database. The configured dashboard is localhost:5173 and backend is localhost:8000; these addresses are not a fresh liveness claim. The plain startup command reads process environment variables and does not automatically load the ignored root .env file.

1. Open the **Indicators** dropdown in the left **Workspace** and create two named SMAs of different lengths, such as 5 and 20 completed candles. In **SMA Strategy**, select the shorter/longer pair and whole-share entry size, then apply the preview. A third SMA cannot replace this explicit pair. Inspection, feed status and Backtesting are also Workspace sections, leaving the chart last in the main area.
2. Inspect a completed candle to see its crossover/action. Arrows are signals, not filled trades. This preview uses the currently loaded paper account; selecting an old candle does not reconstruct the account at that historical time.
3. Open **Backtesting** from the toolbar. **Use loaded chart range** copies the loaded ticker, interval and UTC range, including bars outside the current zoom, plus the applied pair/size when available. Review every setting; chart changes afterward do not change the draft or selected saved result.
4. Select the availability mode, date range, SMA lengths, whole-share size and starting cash, then run. The UI starts with $1,000; the backend default for a request omitting starting_cash is $10,000. Every run starts flat in its own account. It submits no paper/brokerage order and makes no model or history-download call.
5. Inspect final equity/cash/holdings, realized/unrealized/total P&L, return, fills/pending/rejections, equity curve and paginated order/decision/equity audits. Decisions identify both chart time and decision time. A pending order is not a fill; an open position is not automatically closed at the end.
6. Open a saved run or rerun its frozen dataset. The result header/settings/ID identify what is displayed even if form settings or the market chart differ. Reopening survives backend restart/browser reload. Rerun reports whether dataset and result hashes agree. Engine changes can change a future rerun; inspect a reported mismatch.

Errors preserve the earlier labeled result. A retry after a lost response uses the same request ID while the payload is unchanged. Inspect the source/vintage and full result/dataset JSON links below the result. Unavailable prices/valuations stay unavailable; they are not zero returns or guaranteed losses.

## Signal calculation and unfinished candles

An N-candle SMA is the sum of the latest N eligible completed closes divided by N. An unfinished candle or one explicitly marked as having incomplete coverage outputs null and does not enter that window. Until N eligible closes exist, the value is null. Missing completion flags are ineligible. Missing bars are not synthesized; window lengths count eligible observations, not elapsed wall-clock minutes.

A crossover requires two successive comparable fast/slow pairs. For upward, the preceding fast-minus-slow is <=0 and the current difference is >0; downward is >=0 then <0. Equality alone is not a signal. Values within absolute/relative 1e-12 are treated as equal. A null pair breaks comparison, so a newly ready candle may still need another comparable pair. The selected cutoff must itself be ready; an earlier ready signal is never borrowed.

Calculations use Decimal precision 50 internally and emit numeric values. Batch calculation independently sums full windows. Incremental calculation maintains a deque/rolling sum; an append calculates one new output, an unchanged context calculates none, and a revision rebuilds the changed suffix. Input validation, prefix comparison and output copying still traverse bounded context: this is not an O(1) whole-request claim. The cache retains up to 32 contexts. Revisions can change subsequent indicators; executed trades are not rewritten.

`backend.check_sma_engine` compares every tested prefix with pandas rolling(N,min_periods=N,center=False).mean() on the same eligible closes. Numeric comparison uses absolute 1e-10 and relative 1e-12 tolerances. It also checks maximum windows, missing/partial/forming candles, completion, ties, revisions and future-close invariance. That establishes the tested definitions, not agreement with a service using different sessions, adjustment rules, missing-data policy or candle completion.

## Strategy and simulated execution

The backtest enters the configured quantity on an upward crossover while flat, if indicative cash covers the close-price quote. It closes the entire long holding on a downward crossover. Otherwise it holds while invested or waits while flat. It never adds to an existing long position. Unready decisions cannot create an order; an existing pending order prevents another submission.

Submission is not execution. Historical mode executes at a subsequent bar open; recorded mode executes at a later delivered eligible observation receipt. Fill-time cash and share checks can reject an order, including when the next open gaps away from the signal close. The general shared account processes pending orders in submission order without reserving cash/shares. Marks value holdings and never fill orders. Whole shares, cash-only long positions and zero fees/added slippage are assumed; no market depth, spread, latency queue or partial-fill model is implemented.

At a historical boundary, the previous candle's close/decision precedes the next candle's open even when their timestamps are equal. The next open's eligibility does not depend on that candle's eventual completion, high, low or close. A final close decision may leave an order pending because there is no later eligible event inside the run. No extra event or forced liquidation is invented.

## Accounting definitions and known examples

Prices are rounded to cents with ROUND_HALF_UP; cash and cost basis use integer cents. Buys subtract quantity × fill price from cash and add the same amount to total cost basis. Average cost is total basis divided by shares, which can display fractional cents. A partial sale removes its proportional basis rounded to the nearest cent; a full close removes the exact remaining basis. Realized P&L increases by proceeds minus the removed basis.

- Unrealized P&L = shares × usable mark price − remaining basis.
- Equity = cash + marked position value.
- Total P&L = cumulative realized + unrealized P&L.
- Return on starting cash = 100 × (final equity / initial cash − 1). This assumes no deposits/withdrawals within a run; it is not annualized.

Unknown legacy basis or a missing usable mark can make valuation unavailable. Flat known-basis accounts have zero unrealized P&L. No valuation is silently converted to zero. Fees, dividends, interest, borrow costs, taxes and corporate-action accounting are not modeled.

Constructed accounting regression: $1,000 cash; buy 4 at $100 leaves $600/4 shares; sell 1 at $110 leaves $710/3 shares/$10 realized; close 3 at $105 ends $1,025/0 shares/$25 realized/$0 unrealized. The browser and stored ledger agree.

Separate constructed backtest regression: buy 4 at next open $100, close 4 at next open $110, ending $1,040/$40 realized/4.000% return/two fills. A shorter range leaves one pending order without a fill; $100 starting cash rejects the gap-open buy. These deliberately constructed examples test arithmetic and sequencing, not market profitability.

## Data availability modes and range limits

All ranges/times are UTC. The range is [start,end) by candle start; a close decision may occur at end. Up to slow+1 earlier stored bars are requested for warm-up and never trade. Insufficient warm-up remains unready. Data is read in one read-only SQLite transaction, using existing bounded/calendar-aware queries. Nothing is downloaded to make a backtest succeed. Empty/oversized ranges return errors rather than fabricated or silently truncated results.

**Historical bars · fixed vintage:** stored 1m/5m/15m/1h/1d data uses saved versions as of frozen_at (default current UTC). Open is assumed available at bar start, close at bar end. Source precedence, completed native/provider bars and exchange-session aggregation follow the existing history pipeline. The frozen dataset can contain values revised or downloaded after the original trading date. This mode therefore does not establish what a person knew at that original time, even though the strategy processes its fixed input chronologically without using future opens/closes in earlier decisions.

**Recorded availability · 1m:** uses saved candle-revision availability and actual observation receipt times. A contributing receipt is processed before a same-time decision and cannot fill its own signal. Late revisions affect future decisions, not earlier trades. Batched backfills produce only the latest new decision at that availability time. A dataset downloaded after the period alone cannot recreate original arrivals; missing arrival evidence may make a run unavailable. Saved quotes are not guarantees of an executable price.

The frozen vintage cannot be future-dated, and end must not exceed it. Settings require 1 <= fast < slow <=10,000, 1–1,000,000 whole shares and positive starting cash up to $1 trillion. Limits are 10,000 trading bars, 50,000 events and one in-flight backtest. Stored OHLC is used as-is; Yahoo imports are unadjusted. Missing/revised data, corporate actions, dividends, gaps and source limits can materially change outcomes.

## Storage and API handoff

Production is `backend/data/market.db`, initialized by `backend/database.py` with additive migrations through schema 5. Preserve `backend/data/market-observations.sqlite3` as the legacy recovery copy and preserve account/decision IDs. Fixtures always use a separate MARKET_DATABASE. One backend worker owns the collector and serialized writer; no full-history scan is added to the normal chart/tick path.

Schema 5 adds backtest_datasets, backtest_runs and run-scoped backtest_orders/backtest_decisions/backtest_equity. These do not reference paper-account/order IDs. Completed runs are saved atomically; in-flight jobs are not restart-resumable. Dataset SHA-256 identifies canonical frozen input, and result SHA-256 excludes ephemeral run IDs so saved-data reruns can reproduce it. A content hash is an integrity/reproducibility check, not a certificate of original historical knowledge.

- POST /api/backtests creates or returns the result for a unique request_id and normalized settings.
- GET /api/backtests?limit=20&offset=0 lists saved summaries.
- GET /api/backtests/{run_id} returns the immutable saved result.
- GET /api/backtests/{run_id}/dataset returns its hash-verified frozen dataset.
- POST /api/backtests/{run_id}/rerun with a new request_id reruns the saved inputs/settings.

Invalid requests/data return 422, missing runs 404, and reused IDs with changed settings or a busy runner 409. Retrying an identical request ID is idempotent. See the [README request example](../README.md#backtesting-backend-step-4) and [design pipeline](design-pipeline.md) for implementation details.

## Verified results and remaining uncertainty

November 19 local command `node scripts/check-project.mjs` passed all 11 groups: pip check, 24 Python unit tests, SDK memory, seven frontend policy tests, production build, full browser SmokeTest, and focused strategy/chat/comparison browsers. The browser checks compare visible results with the API/SQLite, verify lost-response retry without duplication, paginate audits, and reopen the complete saved result after a real backend restart. UI errors, pending/rejected orders, mobile fit and stale chart responses are covered. See [local command report](evidence/ci-step6-local-1795105633066/local-checks.json) and [backtest observations](evidence/ci-step6-local-1795105633066/backtest-observed.json). These are constructed market/model fixtures.

A read-only running-app inspection of previously cached Yahoo-origin AAPL history for November 13 (SMA 5/20, one-share entries, $1,000 initial cash) matched UI/API result: equity $999.32, cash $642.92, one share, realized −$0.78, unrealized $0.10, total −$0.68, −0.068% displayed return and 23 fills. Saved-data rerun hashes match. [Observed values](evidence/backtest-workspace-1795104683196/observed.json), [desktop performance](evidence/backtest-workspace-1795104683196/saved_aapl_performance.png), [fills](evidence/backtest-workspace-1795104683196/saved_aapl_fills.png), and [mobile](evidence/backtest-workspace-1795104683196/saved_aapl_mobile.png) are preserved. This is cached historical evidence, not a fresh live-source demonstration or original-session availability proof.

What the results establish: the tested SMA definitions, causal event ordering under the stated data mode, known ledger arithmetic, UI/result consistency, isolation, persistence and reproducibility. What they leave uncertain: future profitability, executable market prices, sensitivity to unmodeled costs/actions and data quality, parameter selection bias, and generalization to unseen periods. No out-of-sample or calibrated success-probability claim is made.

The configured [GitHub workflow](../.github/workflows/smoke-test.yml) runs the same command on pushes/PRs/manual dispatch and retains logs/evidence for seven days. Local Python 3.13.17/Node 25.7 passed; hosted Node 24, fresh dependency resolution and artifact upload await a reviewed push. Local passes are not a hosted CI pass.

Part 4.1 still needs one actual regular-session Yahoo message matched through source/receipt IDs, SQLite candle, backend/WebSocket update and visible chart, plus real corresponding volume/unavailable-feed evidence. Actual authenticated assistant chat and two-way voice hardware checks remain separately unverified; a prior real image-model test used synthetic candles. Keys stay on the backend. Agent output remains advisory, and live brokerage execution is outside this implementation.

## Review and resume

Use [current handoff](../handoffs/current.md) for the branch, entry points and pending external checks. No new environment is needed. Reuse `node scripts/check-project.mjs` when implementation changes require the combined regression; the focused options in README avoid repeating unrelated work.

The student's report.md was preserved. Before submitting it, review its old repository URL against the configured remote, complete the unfinished voice-verification sentence, distinguish advisory/reviewer rejection from transport failures, and add this stage's SMA/backtest and CI evidence. Its earlier commit ID still identifies the committed base; it must not be presented as a commit containing the uncommitted implementation. The guide provides factual supporting material without rewriting the student's reflection.
