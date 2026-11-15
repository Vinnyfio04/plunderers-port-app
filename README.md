# Live Market Workplace

## Project overview

Live Market Workplace is a lightweight, TradingView-style local application for people who want to observe markets and make more informed trading decisions. It is aimed especially at less-experienced traders. Yahoo Finance supplies the planned live stream, while the local paper account and agentic helper support practice and explanation. The helper is advisory; the user remains responsible for every trading decision. [Part 4.1 assignment instructions and the current gap assessment](docs/assignment_instructions.md) distinguish the live deliverable from the synthetic CSV practice data.

## Goals

- Present timely market data in a clear, approachable interface.
- Let users watch instruments and explore current market conditions.
- Use an agentic helper to explain signals, uncertainty, and possible actions.
- Keep the frontend, backend logic, and external integrations clearly separated.
- Build repeatable verification into each feature as it is added.

## Technology stack

- **Backend:** Python application logic.
- **Transport:** FastAPI HTTP and, where live updates require it, WebSocket routes.
- **Frontend:** Vue components for user input, charts, and presentation.
- **External services:** Yahoo Finance through yfinance for market observations; OpenAI for optional decision and voice features.

## Current status

The backend owns the Yahoo collector, session scheduling and SQLite recorder independently of browser tabs. The default store is `backend/data/market.db`; startup migrates the old store safely and serves indexed current candles immediately. Empty stores fetch five days of real Yahoo AAPL minute bars; existing stores reconcile an overlapping recent range in the background. The chart reconnects after backend interruptions, shows dated UTC labels and market-closed/next-open status, and appends actual next-session candles without invented overnight bars. Replay reconstructs saved observations in receipt order. CSV is available only through an explicit labeled `MARKET_CANDLE_FILE` development fixture. The expanded offline browser regression passes, including session reopening, chart capture, indicators and paper accounting. An actual regular-session Yahoo observation has **not yet** been matched through SQLite, WebSocket and the visible chart, so Part 4.1 live-streaming evidence remains pending.

## Prerequisites found on this computer

Checked on November 10, 2026:

- Windows 11 (`10.0.26200`)
- PowerShell `7.6.9`
- Python `3.13.17` at `C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe`
- pip `26.2.2` for Python 3.13
- Python `3.12.4` is also installed, but Python 3.13 is the selected interpreter for this project
- Node.js `25.7.0`
- npm `11.10.1`
- pnpm `11.25.0`
- Git `2.51.0.windows.1`
- Google Chrome `157.0.8103.52` was found for the offline browser SmokeTest on November 12, 2026

The plain `python` command currently resolves to a nonworking Windows Store alias in the checked shell. Until PATH/alias behavior is corrected, use the full Python 3.13 path shown above. Yarn and Bun were not found.

## Dependencies

- FastAPI `0.162.3`
- Uvicorn `0.54.0`
- Vue `3.5.45`
- Vite `8.3.7`
- TradingView Lightweight Charts `5.2.1`
- yfinance `1.8.0`
- exchange-calendars `4.13.2`

The backend dependencies are pinned in `backend/requirements.txt`. Frontend dependency declarations and exact transitive resolutions are in `frontend/package.json` and `frontend/package-lock.json`.

## Setup and run instructions

### Install dependencies

Use the existing Python installation; do not create a virtual environment by default.

From the project root:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m pip install -r backend/requirements.txt
Set-Location frontend
npm install
Set-Location ..
```

### Start the backend

Run from the project root in one PowerShell terminal:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The tested backend health URL is `http://127.0.0.1:8000/api/health`.

The tested candle-history URL is `http://127.0.0.1:8000/api/history`.

### Candle history

`GET /api/history` defaults to Yahoo AAPL minute bars and captured observations in SQLite, at the `1m` timeframe. Request another supported timeframe with the query string:

The endpoint now uses recorded observations and receipt-time cutoffs. Explicit CSV fixtures are practice data labeled TEST DATA. Yahoo history fills recent missing minutes; WebSocket observations update forming candles while the app runs. See [assignment_instructions.md](docs/assignment_instructions.md) before presenting Part 4.1 results.

```text
GET /api/history?symbol=AAPL&timeframe=5m
```

Supported timeframe values are `1m`, `5m`, `15m`, `1h`, and `1d`. The response identifies the requested `symbol`, `timeframe`, XNYS calendar, evaluation time, `candles`, and separate `status` entries. Every object in `candles` retains exactly these fields:

```text
timestamp, open, high, low, close, volume
```

Each source row is one minute for one instrument, and its timestamp marks the inclusive start of that minute. Larger timeframes are derived from those same one-minute rows on request. Intraday groups are aligned to the XNYS regular-session open, while a daily candle covers one exchange session and uses its UTC open as the timestamp. The calendar supplies holidays, daylight-saving changes, and early closes.

Each matching `status` object keeps `available_minutes`, `expected_minutes`, `coverage_complete`, `interval_ended`, and `volume_known` outside the six candle fields. A candle volume of `0` is known zero; `null` means one or more included minutes have unknown volume. Gaps do not split a trading session, but they make coverage incomplete.

For replay, add an ISO UTC cutoff. Only source minutes and revisions available at that time are used:

```text
GET /api/history?symbol=AAPL&timeframe=5m&as_of=2026-11-09T14:32:30Z
```

If more than one available one-minute value has the same timestamp, the latest available revision replaces the earlier value before aggregation.

### Market chart

The frontend uses TradingView Lightweight Charts to display one candlestick and one aligned volume bar per UTC source timestamp. The timeframe selector supports `1m`, `5m`, `15m`, `1h`, and `1d`, defaulting to `1m`. Changing it reloads matching backend history and replaces the live WebSocket subscription with the same symbol and interval.

The dashboard shows symbol, interval, data source, source age, upstream feed status, browser-to-FastAPI socket status, and whether the latest candle is still forming. Move the chart crosshair or use the UTC-candle selector to inspect date, time, OHLC, and volume. Unknown volume is shown as `Unknown`, not zero.

### Configured indicators

The dashboard can create named indicator instances for the selected symbol and timeframe. FastAPI exposes the available types and their setting contracts at `GET /api/indicator-types`; saved instances and calculated values are available from `GET /api/indicators`. `POST /api/indicators` validates and stores a new instance.

Every indicator uses the same Python interface:

- **Inputs:** timestamped candles in order, their separate `interval_ended` completion flags, and settings validated for the selected indicator type.
- **Completion rule:** only completed candles enter a rolling window.
- **Output:** exactly one timestamped entry per source candle. Its `value` is numeric when the window is ready, or `null` for a warm-up gap or an incomplete candle.
- **SMA:** input is `close` in price units; output is the arithmetic mean in price units.
- **Rolling price range:** inputs are `high` and `low` in price units; output is `highest high - lowest low` in price-difference units.
- **Window setting:** a whole number from 1 through 10,000, measured in completed candles.

Each named instance stores its own `settings_json` row in the SQLite `indicator_instances` table, keyed to its symbol and timeframe. Reopening the page reloads those rows and recalculates their values from current completed candles. The chart draws a line for each instance, and the candle inspector shows its exact value or `Warm-up gap` at the selected candle.

To run the labeled three-candle fixture with Yahoo disabled and an isolated database:

```powershell
$env:MARKET_LIVE_FEED = '0'
$env:MARKET_DATABASE = (Join-Path (Resolve-Path 'backend').Path 'indicator-browser.sqlite3')
$env:MARKET_CANDLE_FILE = (Resolve-Path 'prompts/data/indicator-fixture.csv').Path
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal, run the tested frontend command `Set-Location frontend; npm run dev`, then open `http://127.0.0.1:5173/`.

The repeatable non-UI calculation and restart-persistence check is:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_indicators --database backend/indicator-test.sqlite3
```

The target database must not already exist so the check cannot silently reuse earlier rows. Its inputs are labeled `TEST DATA — indicator extension verification fixture`.

### Long-only paper account

The local paper account uses the same SQLite database as market observations and indicators. Vue shows cash, AAPL shares, order history, fill links, and rejection reasons. All Vue and future decision-agent actions call the reusable Python function `execute_paper_action` through `POST /api/paper-orders`; `GET /api/paper-account` reloads the persisted state.

Supported actions are:

- `buy`: positive whole-share quantity, accepted pending the next eligible observation;
- `sell`: positive whole-share quantity no larger than the current long position;
- `close`: sells the entire current position;
- `hold`: keeps the existing position and creates no order; and
- `wait`: stays in cash and creates no order.

The simulated fill rule is deliberately simple: an accepted order records the latest paper market-event marker at submission, stays pending, and fills at the first later eligible observed price for that symbol. Prices are rounded to cents and fees are zero. Live Yahoo updates, labeled fixture updates, and replay updates all enter the same paper market-event path. Replay cannot look ahead: only an observation whose replay arrival has occurred can fill an order.

At fill time Python rechecks cash and shares. The account cash, position, fill row, and order status are committed in one SQLite transaction. Each fill records its order, price, source observation ID, receipt ID, paper market-event ID, and execution time. A unique stable `request_id` makes a retry return the existing order without another order or fill.

The same account now keeps append-only P&L history. Buys add to the position's weighted-average cost basis. Partial sales realize the sold shares' difference from that average without changing the remaining per-share cost; a close realizes the remainder. Every fill is valued at its fill price. A newly completed one-minute candle adds a separate valuation row while a position is open. Each row preserves cash, shares, average cost, cumulative realized P&L, unrealized P&L, total P&L, valuation time/source, and links to the underlying fill and/or stored observation. Stable event keys make fill and completed-candle reprocessing idempotent.

If an open position lacks a usable cost basis or valuation price, the dashboard labels its valuation `Unavailable` instead of treating it as zero. Earlier rows remain readable after later valuations and after the position closes.

To run the tested $1,000 labeled browser fixture:

```powershell
$env:MARKET_LIVE_FEED = '0'
$env:MARKET_PAPER_FIXTURE = '1'
$env:PAPER_STARTING_CASH = '1000'
$env:MARKET_DATABASE = (Join-Path (Resolve-Path 'backend').Path 'paper-browser.sqlite3')
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start Vue with `Set-Location frontend; npm run dev`. The fixture-only dashboard control labels every supplied price `TEST DATA — paper account browser fixture`. It is unavailable unless `MARKET_PAPER_FIXTURE=1`.

The repeatable non-UI transaction, idempotency, and restart check is:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_paper_account --database backend/paper-core-test.sqlite3
```

Run the deterministic P&L fixture against a new disposable database path:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_pnl_history --database backend/data/pnl-check.sqlite3
```

The check starts at $1,000, exercises two completed-candle valuations between three fills, verifies a repeated event key remains one row, compares the five expected P&L states with direct SQLite, and reopens the database to prove persistence.

Use a new disposable path. The check refuses to reuse an existing file.

### Ask about a frozen chart

The dashboard's **Ask about chart** button is advisory and never submits a paper order. Select a completed candle first. Vue freezes the symbol, interval, candle range, volume, and indicator lines through that cutoff, then uses Lightweight Charts `takeScreenshot(true)` to export only the chart canvas as PNG. The captured preview remains visible with its snapshot ID and cutoff even if the live chart continues changing.

FastAPI stores the authoritative snapshot in SQLite, loads its configured indicator instances and paper position, and calculates the fast/slow SMA crossover in Python. `POST /api/decisions` rejects a missing snapshot, mismatched symbol/interval/cutoff, invalid base64, a non-PNG payload, or an image smaller than 320×200 with an instruction to recapture.

The provider request follows the [OpenAI Decisions API](https://developers.openai.com/api/reference/resources/decisions/methods/create): one user message contains `input_text`, the actual PNG as an `input_image` data URL, and the snapshot as `input_json.data`. It asks the named choice questions `action`, `crossover`, and `evidence` in one request using `gpt-6-luna`. Answers are validated by name and allowed value. Missing/refused/unreadable answers, insufficient visual evidence, or disagreement with Python make the result ineligible for automated execution. Regardless of eligibility, the feature remains advisory and does not call the paper execution function.

Every successful analysis saves its PNG under the ignored local decision-capture directory and stores the snapshot ID, image hash/path, questions, answers, provider, model, and eligibility result in `decision_records`. `GET /api/decisions/{decision_id}/capture` retrieves the saved PNG.

The decision route now calls an analyst and an independent reviewer once each, with `DECISION_TIMEOUT_SECONDS` (default 30 seconds) applying to each call. Both see the same saved snapshot and PNG. The reviewer also sees the analyst's actual named answers and Python's price, cash, shares, and SMA facts, and chooses `accept`, `reject_insufficient_cash`, `reject_unsupported_signal`, `reject_insufficient_evidence`, or `reject_other`. SQLite retains both outputs and model names under the same decision ID. The dashboard shows the reviewer verdict and a separate Python account/strategy check. Python requires an upward crossover and cash for one share to buy, a downward crossover and shares to sell or close, and a position-appropriate hold or wait. A rejected, missing, timed-out, invalid, or rule-failing result is ineligible. No proposal is submitted as a paper order.

Run the fixed-reply review check from a fresh disposable path with `python -m backend.check_decision_review`; it creates `backend/data/decision-review-test.sqlite3` and checks three saved decisions and zero orders.

### Reviewed paper automation

Start paper automation in Vue with a positive whole-share order size; Stop disables it and cancels its pending orders. A server-side claim reserves each `(account, strategy, symbol, interval, completed candle)` before image capture, so another tab or restart cannot analyze that candle again. Vue uses the same chart-only PNG capture and two-role decision route as the manual question. Missing chart/image or failed analysis is recorded as a skipped automation event. A manual **Ask about chart** click never calls the automation execution route.

An eligible analyst action with reviewer `accept` becomes a pending paper order for the configured buy/sell size; `close` uses the full position, and `hold`/`wait` produce a `no_order` event. The existing simulator fills at the next eligible observed price after submission, with zero fees. Its transaction rechecks the automation generation, five-minute decision deadline, cash, and shares before writing the fill, balances, P&L, and decision ID. It records a skip or rejection reason otherwise. The dashboard traces the decision ID through the event, order, fill, and resulting account. Test automation requires `MARKET_PAPER_FIXTURE=1` and a separate disposable `MARKET_DATABASE`; it cannot use the default observation database.

Run the deterministic integration check from a fresh disposable path:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_paper_automation
```

This creates `backend/data/automation-test.sqlite3`, submits the same fixed approved decision twice, fills four shares at a labeled next price of $100 from $1,000 cash, checks a veto and Stop, and reopens SQLite. For the browser SmokeTest, use a separate `backend/data/automation-browser-final.sqlite3`, `MARKET_PAPER_FIXTURE=1`, `MARKET_LIVE_FEED=0`, `DECISION_PROVIDER=test`, and `backend/data/automation-browser-candles.csv`. Start with its two baseline rows, click Start, add the 14:32 fixture row, wait for the dashboard's decision and pending order, supply the next $100 test price, then click Stop. The observed result and direct SQLite comparison are in `docs/verification.md`. No authenticated provider response was used for the automation fill check.

For a live OpenAI request, set the credential only in the backend environment:

```powershell
$env:DECISION_PROVIDER = 'openai'
$env:OPENAI_API_KEY = '<set outside source control>'
```

Do not put the key in source, prompts, logs, screenshots, or Git. The default provider URL is `https://api.openai.com/v1`; `OPENAI_BASE_URL` is used only when intentionally pointing the same request contract at a local test double.

Prepare the labeled downward-crossover fixture with one command from the project root:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_decision_snapshot --database backend/data/decision-smoke.sqlite3 --captures backend/data/decision-captures-smoke
```

For the browser SmokeTest, start `backend.decision_provider_double` on port 8011, start FastAPI with `DECISION_PROVIDER=test`, `OPENAI_BASE_URL=http://127.0.0.1:8011/v1`, the disposable database above, live feed off, and `MARKET_CANDLE_FILE=prompts/data/indicator-fixture.csv`; then start Vue and click **Ask about chart** at the 14:32 UTC candle. The detailed commands and observed hashes are recorded in `docs/verification.md`.

### Live candle WebSocket

Vue connects through the Vite proxy to:

```text
/ws/candles?symbol=AAPL&timeframe=1m
```

The backend reuses the yfinance `AsyncWebSocket` subscription. Each Yahoo dictionary is written through `MarketRecorder`, recomputed by the one-minute observation aggregator, and passed through the selected history-timeframe aggregator. A candle message has a `candle` object with exactly:

```text
timestamp, open, high, low, close, volume
```

The message carries `symbol`, `interval`, `source`, `feed_status`, source and receipt times, source age, storage IDs, and separate completion/coverage metadata. Equal candle timestamps update the chart in place; a later timestamp appends a candle. A late update for an older timestamp triggers a sorted chart refresh.

Upstream feed status is independent of the FastAPI WebSocket. The page can therefore show Yahoo as disconnected while its local FastAPI socket remains connected.

### Replay a recorded session with Yahoo disconnected

Replay uses the same SQLite observations and backend candle calculations as live mode. The source database is opened read-only; an in-memory recorder reconstructs state in original `receipt_id` order. Source timestamps remain unchanged, so late observations and identifiable revisions alter their original market-time candle when their recorded receipt point is reached.

Start FastAPI from the project root with the live feed disabled:

```powershell
$env:MARKET_LIVE_FEED = '0'
$env:MARKET_DATABASE = (Resolve-Path 'backend/data/market.db').Path
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start the frontend as usual, open `http://127.0.0.1:5173/`, choose **Replay**, select a saved symbol and UTC range, select a timeframe, and press **Start Replay**. The page labels the chart `Replay`, shows the source observation and original receipt time, displays Yahoo as disconnected, and reports the stored count before and after the read-only run. An empty range shows `This selection has no recorded observations.`

For the deterministic verifier, first create a separate ignored test database once, then start Uvicorn with `MARKET_DATABASE` pointing at it:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_replay_session --database backend/replay-test.sqlite3 --create-test-session
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_replay_websocket
```

The first command labels every constructed input as test data. The second command expects Uvicorn on port 8000 with the live feed off, runs the same WebSocket selection twice, compares the final 15:00 UTC candle with `close=102` and `volume=12`, checks an empty range, and confirms the stored observation count remains five.

### Yahoo Finance stream check

The backend includes a bounded yfinance WebSocket check for one ticker. It defaults to `AAPL`, requires no Yahoo login, and exits after its configured receipt timeout plus a short bounded cleanup period.

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.yahoo_stream --ticker AAPL --timeout 20
```

If Yahoo sends an update, the command prints the ticker, price, source timestamp, backend UTC receipt timestamp, and available `day_volume` or `last_size` fields. If no update arrives, it reports whether the socket opened and sets `receipt_verified` to `false`.

The application does not accept or store Yahoo credentials. A personal Yahoo watchlist can be created or managed separately on the Yahoo Finance website, where the user enters credentials directly.

For deterministic local interface verification only, set `MARKET_TEST_FEED=1` before starting Uvicorn and point `MARKET_DATABASE` at a disposable SQLite path. This replays records labeled `TEST DATA — recorded interface verification input`; it is not live market data.

### SQLite market recorder

The default local database path is:

```text
backend/data/market.db
```

Initialize it from the project root with:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.market_store --database backend/data/market.db --init
```

The Yahoo receiver uses that path by default. An alternate path can be supplied with `--database`:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.yahoo_stream --ticker AAPL --timeout 20 --database backend/data/market.db
```

The recorder stores source fields as canonical JSON plus indexed ticker, source-time, price, and volume values. A SHA-256 hash of the canonical source JSON recognizes an exact repeat regardless of dictionary key order. Exact repeats share one `observations` row but receive separate, ordered `receipts` rows.

A changed payload at the same ticker and source time is retained as another observation. The recorder does not assume that it is a correction. When the feed or caller can reliably identify a correction, it supplies `supersedes_observation_id`; the revised row points to the earlier row instead of overwriting it. Readers can avoid counting exact repeats by reading `observations`, while `receipts ORDER BY receipt_id` provides the complete arrival audit trail. Source-time columns remain separate from receipt order so late messages stay identifiable.

### Aggregate stored one-minute candles

Generate one ticker's candles from the stored observations with:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.candle_aggregation --database backend/data/market.db --ticker AAPL --as-of 2026-11-09T15:01:00Z
```

Each object in `candles` has exactly `timestamp`, `open`, `high`, `low`, `close`, and `volume`. The separate `minute_status` array reports whether each UTC minute has ended as of the requested time.

Prices are ordered by source time, so a late observation is inserted into its original market-time position when the candle is recalculated. An identifiable correction excludes its superseded value from the derived candle while preserving both database rows. A changed message that is not identified as a correction remains a distinct observation. For equal source timestamps where the feed supplies no finer ordering, observation ID is the stable tie-breaker.

Minute volume is the last available cumulative session total inside the minute minus the last available cumulative total before the minute. It is returned as `null` (unknown) when the baseline is unavailable, the minute has no cumulative total, or the observed cumulative total decreases and indicates a session reset.

### Start the frontend

Run from the project root in a second PowerShell terminal:

```powershell
Set-Location frontend
npm run dev
```

Open `http://127.0.0.1:5173/`. The frontend proxy health URL is `http://127.0.0.1:5173/api/health`.

### Stop the services

In each service terminal, press `Ctrl+C`. This stop procedure was tested for both Uvicorn and Vite. Stop the frontend and backend separately; neither command edits source files.

### Offline browser SmokeTest

From the project root, with the existing backend requirements and locked frontend packages installed, run **one command**:

```powershell
node scripts/smoke-test.mjs
```

This starts FastAPI and Vue on temporary localhost ports, waits for both, opens the installed Chrome (or Edge) in headless mode, and drives the real dashboard. It seeds a fresh SQLite account and recorded session under ignored `backend/data/smoke-runs/` and uses a local model test double with no provider credentials or Yahoo connection. The browser replays observations, creates and edits an SMA, captures a chart PNG, checks a model failure, and runs approved buy/sell/close automation with a veto, duplicate candle, and Stop. It compares displayed values with direct SQLite queries. A missing expected result returns a nonzero exit code. Browser and service processes close on success or failure; a failed run retains an ignored screenshot and database for diagnosis, while a passing run removes its temporary folder. Set `SMOKE_PYTHON` or `SMOKE_CHROME` to an installed executable path only if autodetection fails. The same command runs on every push in `.github/workflows/smoke-test.yml` after the workflow installs the already-declared dependencies in its temporary Windows runner.

Expected final fixture state: `$1,025` cash, zero shares, `$25` realized and `$0` unrealized P&L, three fills, and no extra order after Stop. The live Yahoo feed, authenticated image-model call, and two-way voice hardware check remain separate from this offline SmokeTest.

### Talk about a saved paper decision

The dashboard lists saved AAPL decisions and their recorded analyst proposal, reviewer verdict, and paper outcome. Select one and click **Start voice** to request microphone permission. The browser sends its WebRTC offer and decision ID to `POST /api/voice-sessions`; FastAPI reads that decision from SQLite and exchanges the offer with OpenAI GPT-Live using `OPENAI_API_KEY` in the backend environment. The browser receives spoken answers on the WebRTC audio track and displays input/output transcript fragments. The session has only a read-only summary of the chosen decision and cannot place an order. **End voice** stops the microphone; a failed connection also releases it. The browser needs localhost or HTTPS, a microphone, a speaker, and a project API key with GPT-Live access. The initial session has provider usage charges.

Use the existing ignored root `.env` for the key. In the backend terminal, load its assignment into that process without printing it, then run the tested Uvicorn startup command above. For the existing labeled paper fixture, the tested local setup used:

```powershell
$env:MARKET_DATABASE = (Resolve-Path 'backend/data/automation-browser-final.sqlite3').Path
$env:MARKET_LIVE_FEED = '0'
$env:MARKET_PAPER_FIXTURE = '1'
$env:OPENAI_API_KEY = ((Get-Content '.env' | Where-Object { $_ -match '^OPENAI_API_KEY=' } | Select-Object -First 1) -split '=',2)[1].Trim().Trim('"').Trim("'")
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start Vite using the frontend command above, then open `http://127.0.0.1:5173/`. This database contains **TEST DATA**, including decision `dec_f0d80fa50639431a8bbbec7cf9150205`, an accepted buy proposal and a simulated four-share fill. To repeat the offline provider-contract check without a microphone or API call:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_voice_session --database backend/data/automation-browser-final.sqlite3 --decision-id dec_f0d80fa50639431a8bbbec7cf9150205
```

The live voice SmokeTest requires a person with a microphone and speaker: run the two local services, open the dashboard, click **Start voice**, ask “What did the agents decide for this symbol?” and then “What happened to the paper account?”, compare the spoken replies and visible captions with SQLite, click **End voice**, and check that the browser microphone indicator turns off. The in-app browser microphone request remained pending during this setup; this live hardware check is recorded as pending in `docs/verification.md`.

### Verify the connection

With both services running:

```powershell
$backend = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health'
$frontend = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/api/health'
$backend.StatusCode
$backend.Content
$frontend.StatusCode
$frontend.Content
$backend.Content -ceq $frontend.Content
```

The tested result is HTTP `200` from both URLs, the JSON body `{"status":"ok","service":"backend"}`, and a final comparison result of `True`.

The verified interpreter check is:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' --version
```

Expected output:

```text
Python 3.13.17
```

Repeatable checks and their detailed results are in [docs/verification.md](docs/verification.md).

## Folder map

```text
live-market-workplace/
|-- README.md
|-- AGENTS.md
|-- .github/
|   `-- workflows/smoke-test.yml
|-- backend/
|   |-- candle_aggregation.py
|   |-- check_candle_aggregation.py
|   |-- check_decision_snapshot.py
|   |-- check_decision_review.py
|   |-- check_market_store.py
|   |-- check_timeframe_history.py
|   |-- check_live_candles.py
|   |-- check_indicators.py
|   |-- check_paper_account.py
|   |-- check_paper_automation.py
|   |-- check_pnl_history.py
|   |-- check_replay_session.py
|   |-- check_replay_websocket.py
|   |-- check_voice_session.py
|   |-- decision_provider_double.py
|   |-- decisions.py
|   |-- data/
|   |   `-- automation-browser-candles.csv
|   |-- live_candles.py
|   |-- indicators.py
|   |-- main.py
|   |-- market_store.py
|   |-- paper_trading.py
|   |-- replay_session.py
|   |-- requirements.txt
|   |-- smoke_fixture.py
|   |-- smoke_state.py
|   |-- timeframe_history.py
|   |-- voice.py
|   `-- yahoo_stream.py
|-- frontend/
|   |-- src/
|   |   |-- chartAdapter.js
|   |   |-- main.js
|   |   `-- style.css
|   |-- index.html
|   |-- package.json
|   |-- package-lock.json
|   `-- vite.config.js
|-- docs/
|   |-- design-pipeline.md
|   `-- verification.md
|-- prompts/
|   |-- data/
|   |   `-- sample-candles.csv
|   |-- 01-generic-project-startup.md
|   |-- 02-connect-vue-fastapi.md
|   |-- 03-serve-candle-history.md
|   |-- 04-display-candles-with-lightweight-charts.md
|   |-- 05-yahoo-finance-stream.md
|   |-- 06-record-yahoo-updates-sqlite.md
|   |-- 07-aggregate-observations-into-candles.md
|   |-- 08-history-timeframes.md
|   |-- 09-live-chart-websocket.md
|   |-- 10-recorded-session-replay.md
|   |-- 11-extensible-indicators.md
|   |-- 12-long-only-paper-account.md
|   |-- 13-paper-account-pnl-history.md
|   |-- 14-ask-about-chart.md
|   |-- 15-two-role-decision-review.md
|   |-- 16-reviewed-paper-automation.md
|   |-- 17-decision-voice-conversation.md
|   `-- 18-offline-browser-smoketest.md
|-- scripts/
|   `-- smoke-test.mjs
`-- handoffs/
    |-- create-handoff.md
    `-- current.md
```

See [docs/design-pipeline.md](docs/design-pipeline.md) for planned responsibilities and data flow.


## Recorded live history verification

Use the normal startup command with `MARKET_LIVE_FEED=1` and no `MARKET_CANDLE_FILE` override for recorded/live market data. `MARKET_LIVE_FEED=0` keeps recorded history and Replay available while disabling the subscription. No Yahoo login is required.

Run `python -m backend.check_recorded_history` using the full Python executable above. It creates and removes a disposable TEST DATA database and checks empty history, receipt cutoffs, late/revised candles, timer completion, unknown volume, upstream disconnect, and persistence after reopen. Run `node scripts/smoke-test.mjs` for the full offline browser regression.

The additive `candle_states` table retains emitted OHLCV/completion states, evaluation time, symbol, interval, and candle timestamp. Volume uses cumulative `day_volume` differences with a same-date baseline in the preceding minute. Missing totals, gaps, and resets yield Unknown. Quote `last_size` is preserved but is not summed as if it were a complete trade tape. Real volume remains dependent on the feed supplying usable totals.


## Yahoo startup history and volume reconciliation

Use the tested backend and Vue startup commands above. With `MARKET_LIVE_FEED=1`, no `MARKET_CANDLE_FILE` override, and no test feed, FastAPI fetches five days of unadjusted regular-session AAPL minute bars for an empty store. Existing stores fetch from five minutes before the latest saved minute, bounded by Yahoo's recent-history window. Reconciliation runs every 60 seconds during an open session, with bounded final attempts after close and calendar-based waiting until the next open. Existing yfinance and SQLite suffice; no new dependencies or credentials are required. An unavailable download keeps cached history and shows an error notice. With live disabled, startup uses the saved bars without contacting Yahoo.

The existing database now also holds `yahoo_minute_bars` and `yahoo_history_fetches`; backend startup initializes them additively. Completed downloaded bars replace the corresponding observed minute, including its volume. Provisional bars may be extended by newer quotes, with volume marked Unknown until reconciliation. Bar volume and tick-derived volume are never added. Versions retain their fetch times; raw quote observations remain separate. The existing recorded-session Replay selects quote observations; imported bars are available through history and its as-of cutoff rather than being fabricated as tick receipts.

The dashboard displays Market open/closed and the next regular-session open independently of feed connectivity. On a closed market it displays the last available session, not synthetic current-time candles.

Run the tested focused command from the root using the selected Python executable:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_yahoo_history
```

This uses a disposable database and labeled TEST DATA for provisional tick overlays, volume replacement, duplicate completed downloads, revisions/reverts, as-of availability, cache on failure, and open/closed/early-close status. The full regression remains `node scripts/smoke-test.mjs`. Actual fetched-history and browser comparisons are recorded separately in `docs/verification.md`; a real in-session streaming check is still pending.


## Continuous chart and market.db

Clicking AAPL in Live / History loads its recent saved sessions even when the market is closed. Company selection requests `/api/history?symbol=AAPL&timeframe=1m&recent=true`: saved candles appear immediately, and a missing cache gets a bounded Yahoo history attempt. Concurrent requests share a download and repeated clicks are throttled. Unavailable Yahoo history preserves cached candles; the UI retries backend failures without requiring a new live tick. Indicators and account panels load independently of the chart. Only AAPL currently has a selectable live/history integration; saved-session buttons remain Replay controls.

Vite's API proxy uses a built-in Node HTTP keep-alive agent. On this installed local FastAPI stack, an upstream `Connection: close` request could reset before the response body was delivered, leaving a blank chart despite saved history. Keep the API proxy agent when changing development configuration; the browser regression checks all 1,950 fixture candles through the frontend URL. No additional package is needed.

The normal database is now `backend/data/market.db`. On first startup, an existing `backend/data/market-observations.sqlite3` is copied with SQLite's backup API, all project tables and IDs are preserved, and versioned migrations create the indexed current-candle tables. The old file remains a recovery copy. An existing recognized `market.db` is upgraded idempotently; unrelated databases are rejected. Databases, WAL/SHM files and owner-lock files are ignored by Git.

For explicit initialization/migration with the backend stopped, use the tested command from the project root:

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.database
```

Use the existing Uvicorn and Vue startup commands above, with one Uvicorn worker. The backend owns the AAPL collector even with no browser open. It schedules regular sessions with the exchange calendar, retries disconnects with backoff, performs incremental overlapping history reconciliation, and makes bounded final fetches after close. The local socket reconnects automatically after a backend restart. On a closed market the last real candles stay visible and the next open is shown; no overnight candles are invented. At open the next actual minute appends after the previous session. Source timestamps stay UTC and axis/crosshair labels use `MM/DD/YYYY HH:mm` with a visible UTC label.

`GET /api/history` returns at most 2,000 candles by default, with `limit` (1..2000), timezone-qualified `before` and `start` bounds, a `next_before` cursor and a committed revision watermark. Scroll left to load older pages; the browser retains at most 6,000 candles and evicts later pages while reviewing older history. **Latest · UTC** returns to the current window. Indicator/snapshot warm-up uses a bounded backend context derived from each indicator's validated window, independent of browser scrolling.

Current candles use typed `candles_1m` columns with a composite instrument/time primary key. Only affected minutes and baseline-dependent neighbors are recomputed. Revisions/provenance and original receipts remain queryable; larger intervals derive from effective minute rows. `MARKET_DATABASE` continues to select a separate test database. The existing quote-replay workflow remains receipt-ordered and read-only for the recorded source.

The expanded single-command regression is still `node scripts/smoke-test.mjs`. It now includes migration/ownership/recovery, a million on-disk minute candles with quote/revision audit data, Friday/Monday adjacency, desktop/mobile dated canvas labels, backend restart/socket reconnect, and commit-to-screen latency. Run the focused backend checks with `python -m backend.check_continuous` and `python -m backend.check_yahoo_history` using the selected Python executable. All deterministic events and provider replies in those checks are labeled TEST DATA; actual Yahoo history and open-session evidence are recorded separately in `docs/verification.md`.
