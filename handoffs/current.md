# Plunderer's Port — current handoff

Updated November 20, 2026 (America/New_York). All seven approved SMA/simulation/backtesting implementation stages are complete locally. The student explicitly approved committing and pushing all current changes to workplace-chatbot on November 20 (prompt 59). Use Git HEAD, branch tracking and the workflow run for the final publication/CI state; the earlier dated uncommitted notes describe the pre-approval snapshots. No live brokerage execution is enabled. This status does not declare Part 4.1 live streaming complete.

## Checkout and review boundary

- Root: C:\Users\Owner\Desktop\School Work\5 Fall 2026\IST 402 - Vibe Coding\live-market-workplace.
- Branch: workplace-chatbot. Remote: https://github.com/Vinnyfio04/plunderers-port-app.
- Prior committed base: 3866209f6d28b842db2bc56e262ae2e05f7d578c, the branding commit, predates this feature publication. Git log identifies the final feature commit. No PR or manual workflow dispatch is requested; a normal push triggers the configured workflow.
- Preserve all existing student work, especially report.md. The final documentation leaves that file unchanged. Review its old repository link, incomplete voice sentence and implementation/evidence wording with the student before submission.
- Use [AGENTS.md](../AGENTS.md). Review proposed/completed changes before committing; never commit unreviewed work. No new environment or dependency installation is needed.

## Read first

- [Strategy workstation guide](../docs/strategy-workstation.md): operation, acceptance, SMA/completion semantics, order execution, accounting formulas, availability modes, results and limits.
- [README](../README.md): tested startup/API examples and check commands.
- [Design pipeline](../docs/design-pipeline.md): shared calculations, history/collector paths, isolated runner/storage and UI/API responsibilities.
- [Verification](../docs/verification.md): actual commands/results, failed and passing checks, fixture provenance and remaining unrun checks. Preserve its chronological history.
- [Part 4.1 acceptance](../docs/assignment_instructions.md): original live requirements and current evidence gap, separately from the strategy extension.
- [Previous handoff snapshot](2026-11-19-before-final-handoff.md): preserved earlier dated context; it is not the current status.

## Implemented behavior and source entry points

- November 20 (prompt 58): removed the selected O/H/L/C/Vol strip from the main chart header and its unused CSS. Raw candle values remain in Workspace's Inspect a candle. Instrument/source/status, chart, backend and trading behavior are unchanged. Updated running-UI capture: docs/evidence/workspace-layout-1795198177414/workspace_indicators.png. No dependency or backend restart required.
- Latest layout change (prompt 57): Indicators is its own left Workspace dropdown. Candle inspection, feed status, Backtesting and attribution were moved into Workspace so the chart is the final main-column element; narrow screens place Workspace before the chart. Sidebar forms and toolbar wrapping fit 1009px/390px viewports. Focused create/update/SQLite checks, full SmokeTest and build pass; see the latest verification entry and docs/evidence/workspace-layout-1795125216872/ for the actual running UI screenshot. No backend/dependency/trading change or restart.
- frontend/src/main.js and chartAdapter.js: workstation, bounded history/cache, saved indicators, explicit fast/slow SMA pair, whole-share entry preview, crossover arrows, assistant chat and reviewed paper workflow. The selected older candle still uses the current paper account for preview; use Backtesting for historical account state.
- backend/sma_engine.py and indicators.py: shared trailing batch/incremental SMA and crossover; chart, preview, frozen assessment and backtester use the same definitions. Warm-up/unfinished/explicitly partial data outputs null; missing pairs break crossover comparison. Near-equality is a tie. EMA/MACD/RSI are not implemented.
- backend/accounting.py, paper_trading.py and simulation_account.py: shared integer-cent HALF_UP fill/valuation rules, weighted-average basis and realized/unrealized P&L. Existing SQL paper ledger retains its IDs/transactions. Each SimulationAccount is separate and has no live account/database reference.
- backend/backtesting.py: long-only SMA entry/close rules with warm-up, causal event order, next-open or later-receipt execution, fill-time cash/share rejection and no final liquidation. One pending order at a time; no extra buying while long. Historical-bar fixed-vintage assumptions are distinct from recorded 1m availability.
- backend/backtest_store.py and main.py /api/backtests routes: bounded read-only dataset freeze, atomic saved settings/datasets/trades/decisions/equity, hashes, idempotent request IDs, list/get/dataset/rerun. No provider download/model call or paper order. Completed runs persist; in-flight runs do not resume.
- frontend/src/BacktestPanel.js: isolated draft/result state, saved-run browsing/rerun, equity/P&L/cash/position metrics, paginated audit tables, source/vintage/hash details and limitations. Chart changes and failures cannot relabel the selected result.
- backend/chat_agent.py: backend Agents SDK tools for rules and frozen-chart assessment; unclear requests ask for clarification. Rules alone do not assess a chart. Tool records expose returned results; ticker/time/choice/available probability and chart preview/decision share that result. Stale context is rejected. Per-conversation earlier assessments are isolated by ticker and Live/Replay mode. New chat/reload starts a separate conversation; backend restart loses the process-local memory. No trading tool.
- scripts/check-project.mjs, smoke-test.mjs, backtest-browser-checks.mjs and .github/workflows/smoke-test.yml: repeatable core/build/browser checks, new restart/retry/pagination coverage, push/PR/manual workflow and fixture-only artifacts.

## Storage and environment

Production is backend/data/market.db through backend/database.py and additive versioned migrations, currently schema 5. Preserve backend/data/market-observations.sqlite3 as the legacy recovery copy. Preserve all account/decision/order IDs. Use one Uvicorn worker and the backend-owned collector/serialized writer. Fixtures require a different MARKET_DATABASE; full-history scans stay out of normal tick/chart paths.

A November 19 read-only metadata query found schema 5, one paper account, zero paper orders/fills, five decision records and two backtest runs. These counts are storage evidence, not a current feed/freshness claim. November 18 migration verification compared complete protected account/decision table fingerprints before/after migration and saved backtests; all matched. No production data was changed by the final documentation task.

Existing local environment: Python 3.13.17 at C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe; Node 25.7.0/npm 11.10.1; OpenAI 3.52.0 and Agents 0.24.0 pinned in backend/requirements.txt. Reuse installed packages. Hosted CI selects Python 3.13/Node 24 and installs the existing manifests/lockfile in its temporary runner. Local passes do not prove hosted runtime/package resolution.

From the project root, start the backend with the tested command (first identify existing listeners; do not launch a duplicate):

~~~powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
~~~

In another terminal:

~~~powershell
Set-Location frontend
npm run dev
~~~

Configured URLs: dashboard http://127.0.0.1:5173/ and backend docs http://127.0.0.1:8000/docs. These are not a fresh liveness assertion. Stop services in their owning terminals. The plain command reads process environment and does not automatically load root .env. Load any existing key privately for authenticated model/voice features; never print it or put it in frontend/source/prompts/logs/screenshots. Clear fixture flags and database overrides before normal startup. No restart is required for step 7's documentation-only changes.

## Latest verification and evidence

November 19: node scripts/check-project.mjs passed all 11 groups in about seven minutes: pip check; eight SMA/pandas-reference, eight accounting and eight causal-backtest tests; SDK memory; seven frontend policy tests; build; full SmokeTest; strategy, chat and conversation-comparison browsers. All used existing tools and disposable stores/test providers. [Compact check report](../docs/evidence/ci-step6-local-1795105633066/local-checks.json) and [backtest observations](../docs/evidence/ci-step6-local-1795105633066/backtest-observed.json) retain actual results. A deliberately missing interpreter returned exit 1, saved a failed summary and recorded unrun checks; this is an expected failure-path test, not a remaining defect.

New UI checks prove duplicate-free retry after a saved response is lost, second audit pages matching 56 decisions/58 equity events, and complete saved results/IDs surviving a real backend restart. The known backtest ends $1,040/$40 realized/two fills; existing paper regression ends $1,025/zero shares/$25 realized/three fills. Pending/rejected orders, error retention, mobile fit and delayed chart-context responses pass. Shared 1/2 SMAs give upward/13/11 in chart/preview/frozen assessment. Chat tests verify rule-only tools, wait/82% at 14:32, buy/91% at 14:33 compared to the earlier result, both times, and New chat isolation. No authenticated model call is implied.

Read-only actual cached AAPL evidence: [observed values](../docs/evidence/backtest-workspace-1795104683196/observed.json) and [performance screenshot](../docs/evidence/backtest-workspace-1795104683196/saved_aapl_performance.png). November 13 SMA 5/20 yields $999.32 equity, -$0.68 total P&L and 23 fills; UI/API/saved result agree and saved-data rerun hashes match. This is cached fixed-vintage Yahoo-origin history, not original-session knowledge or a fresh live quote. Prior failed fixture checks and their corrections remain in verification.md. Existing pandas/FastAPI deprecation warnings are non-fatal.

Step 7 changed documentation only. The latest application suite was reused rather than rerun; final checks cover document links/consistency, report preservation and git diff --check. See the final verification entry for their observed results.

## Remaining checks and next review

1. Review the complete dirty diff and student's report before deciding what to commit. Once reviewed/committed/pushed, inspect the hosted workflow and artifact upload. No hosted CI pass is claimed now; do not infer one from the old base commit's skip-ci tag or the local suite.
2. Complete the Part 4.1 live-source chain during a bounded regular-session observation: actual Yahoo message -> observation/receipt IDs -> effective candle -> backend/WebSocket -> visible chart. Record time/source/age/completion and corresponding volume or its absence. Show real upstream failure/staleness separately from the still-connected local socket, retaining cached history. Do not substitute a download or fixture.
3. Verify authenticated SDK chat if requested; keep that separate from the earlier successful real image-model call on synthetic candles. When working hardware is available, verify two-way voice and microphone release.
4. Further indicators, parameter research, corporate-action/cost/executable-price models or live brokerage execution are new scope. Backtest results establish tested rules/accounting/reproducibility under stated assumptions, not future profitability. Do not enable live trades without a separately reviewed requirement.
