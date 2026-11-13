# Verification log

Record checks in chronological order. Include the command, expected result, observed result, and status. Record failures as well as passes.

## 2026-11-10 — Startup scaffold

### Project-root inspection

- **Command:** `Get-ChildItem -Force`; `rg --files`; `git status --short --branch`
- **Expected:** Identify existing files and repository state before editing.
- **Observed:** The selected root was empty. No dependency files, lockfiles, prompts, or `AGENTS.md` existed. Git reported `fatal: not a git repository`.
- **Status:** PASS — the state was identified before edits; no existing work needed merging.

### Initial Python launcher check

- **Command:** `python --version`; `py --version`
- **Expected:** Identify an active Python interpreter.
- **Observed:** `python` resolved to a Windows Store alias that could not be launched in the checked environment. `py` initially reported `No installed Python found!`.
- **Status:** FAIL — the aliases did not reveal the installed interpreter.

### Python package-manager check

- **Command:** Check `uv`, `conda`, `mamba`, `micromamba`, `poetry`, `pipenv`, `pip`, `pip3`, and `pyenv`; inspect active-environment variables.
- **Expected:** Identify any active Python environment or environment manager.
- **Observed:** No environment variable was active and none of the listed manager commands was found on PATH.
- **Status:** PASS — the available environment state was determined; no environment was created.

### Python installation request

- **Command:** `winget install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements`
- **Expected:** Install Python 3.13 if missing, or report the installed version.
- **Observed:** Winget reported that Python 3.13 was already installed, with no newer package available. A read-only Winget/registry inspection located Python `3.13.17` at `C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe` and Python `3.12.4` at `C:\Users\Owner\AppData\Local\Programs\Python\Python312\python.exe`.
- **Status:** PASS — no project files, manifests, or lockfiles were changed by this command.

### Selected Python interpreter

- **Command:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' --version`
- **Expected:** Python 3.13 responds from the selected existing installation.
- **Observed:** `Python 3.13.17`.
- **Status:** PASS

### pip

- **Command:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m pip --version`
- **Expected:** pip is available through the selected interpreter.
- **Observed:** pip `26.2.2` in the Python 3.13 user installation.
- **Status:** PASS

### Planned backend package availability

- **Command:** Use Python `importlib` to inspect `fastapi`, `uvicorn`, and `pydantic` in Python 3.13.
- **Expected:** Report availability without installing or changing dependencies.
- **Observed:** FastAPI, Uvicorn, and Pydantic are not installed.
- **Status:** PASS — availability was checked; installation is intentionally deferred until versions and manifests are approved.

### JavaScript and Git toolchain

- **Command:** `node --version`; `npm --version`; `pnpm --version`; `git --version`
- **Expected:** Identify the existing frontend and source-control tools.
- **Observed:** Node.js `25.7.0`, npm `11.10.1`, pnpm `11.25.0`, and Git `2.51.0.windows.1`. Yarn and Bun were not found.
- **Status:** PASS

### Dependency and lockfile inspection

- **Command:** Search recursively for `pyproject.toml`, `requirements*.txt`, `Pipfile`, `Pipfile.lock`, `poetry.lock`, `uv.lock`, `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, and `bun.lockb`.
- **Expected:** Identify existing dependency definitions before changing dependencies.
- **Observed:** No dependency manifests or lockfiles existed.
- **Status:** PASS

### Scaffold structure

- **Command:** Use PowerShell `Test-Path` for every required directory and file, then enumerate the actual tree.
- **Expected:** `backend/`, `frontend/`, `docs/`, `prompts/`, and `handoffs/` exist with all requested documentation files; no unapproved dependency manifest or lockfile exists.
- **Observed:** Every required path and README link target existed. `backend/` and `frontend/` were empty as intended. No dependency manifest or lockfile was found. The selected Python interpreter still returned `Python 3.13.17`.
- **Status:** PASS

## Checks still required

- No live-data check can run until a market-data provider and credentials approach are selected.
- No agent-helper check can run until its model/provider and expected behavior are selected.

## 2026-11-10 — Vue-to-FastAPI connection

### Approved dependency installation

- **Commands:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m pip install fastapi==0.162.3 uvicorn==0.54.0`; `npm install --save-exact vue@3.5.45`; `npm install --save-dev --save-exact vite@8.3.7` from `frontend/`.
- **Expected:** Install the approved versions into the existing Python 3.13 environment and local frontend project; create/update the approved manifests and lockfile.
- **Observed:** FastAPI `0.162.3` and Uvicorn `0.54.0` installed into the selected Python environment. Vue `3.5.45` and Vite `8.3.7` installed under `frontend/node_modules/`; `frontend/package.json` and `frontend/package-lock.json` contain the dependency declarations and resolutions. npm reported zero vulnerabilities.
- **Status:** PASS

### Import and package resolution

- **Commands:** Import FastAPI and Uvicorn with the selected interpreter; run `npm ls vue vite --depth=0` in `frontend/`.
- **Expected:** Resolve the four approved direct dependencies at their exact versions.
- **Observed:** FastAPI `0.162.3`, Uvicorn `0.54.0`, Vue `3.5.45`, and Vite `8.3.7`.
- **Status:** PASS

### Frontend production build

- **Command:** `npm run build` from `frontend/`.
- **Expected:** Vite builds the minimal Vue application without an error.
- **Observed:** Vite transformed 10 modules and produced `frontend/dist/` successfully in 162 ms.
- **Status:** PASS

### AutoLoop startup correction

- **Cycle 1:** A background-process launch timed out waiting for `http://127.0.0.1:8000/api/health`. The module imported correctly and exposed `/api/health`; captured service stderr was empty. The launch method, not source, was identified as the likely cause.
- **Cycle 2:** Managed terminal sessions exposed the actual environment error: sandboxed processes were forbidden from binding or accessing local sockets. The same source and commands were rerun with localhost permission; both services started normally. No source edit was needed.
- **Status:** PASS after two correction cycles.

### Direct and proxied health request

- **Backend URL:** `http://127.0.0.1:8000/api/health`
- **Backend status/body:** `200`; `{"status":"ok","service":"backend"}`
- **Frontend URL:** `http://127.0.0.1:5173/api/health`
- **Frontend status/body:** `200`; `{"status":"ok","service":"backend"}`
- **Expected:** Both URLs return HTTP 200 and byte-for-byte identical JSON.
- **Observed:** The response bodies matched exactly (`True`).
- **Status:** PASS

### Backend dependency proof

- **Action:** Stop Uvicorn while leaving Vite running, then request `http://127.0.0.1:5173/api/health` again.
- **Expected:** The frontend address fails because Vite must contact FastAPI.
- **Observed:** The frontend address returned HTTP `502` with an empty body; Vite logged `ECONNREFUSED 127.0.0.1:8000`.
- **Status:** PASS

### Recovery after backend restart

- **Action:** Restart Uvicorn, then request both the direct and proxied health URLs.
- **Expected:** Both return HTTP 200 with identical JSON again.
- **Observed:** Both returned `200` and `{"status":"ok","service":"backend"}`; the body comparison returned `True`.
- **Status:** PASS

### Browser-visible SmokeTest

- **Command:** Start the backend and frontend using the README commands, then open `http://127.0.0.1:5173/` in a browser.
- **Expected:** The visible Vue page shows the FastAPI health JSON.
- **Observed:** The page displayed “Frontend-to-backend connection” and the visible JSON fields `"status": "ok"` and `"service": "backend"`.
- **Status:** PASS

### Service shutdown

- **Command:** Press `Ctrl+C` in each running service terminal.
- **Expected:** Uvicorn performs application shutdown and Vite stops listening.
- **Observed:** Uvicorn logged shutdown and application-shutdown completion; both managed service sessions ended.
- **Status:** PASS

### Final dependency consistency

- **Commands:** Run `python -m pip check` with the selected Python executable; run `npm ls --depth=0` and `npm run build` from `frontend/`.
- **Expected:** No broken Python requirements, exact direct frontend dependencies, and a repeatable successful build.
- **Observed:** pip reported `No broken requirements found.` npm resolved Vue `3.5.45` and Vite `8.3.7`; the repeated Vite build transformed 10 modules and completed in 107 ms.
- **Status:** PASS

### Remaining checks

- No live-market-data test can run until a provider and credentials approach are selected.
- No agent-helper test can run until its model/provider and expected behavior are selected.
- No persistence check is required yet because the health feature stores no data.

## 2026-11-10 — Local candle history

### Source-file inspection

- **Command:** Inspect `prompts/data/sample-candles.csv` and verify the selected Python interpreter and built-in `csv` module.
- **Expected:** A supplied file with exactly `timestamp,open,high,low,close,volume` and the three requested rows; Python 3.13 can import `csv` without a dependency change.
- **Observed:** The supplied file matched all six fields and all three rows exactly. Python `3.13.17` loaded `csv` from its standard library. No dependency or manifest change was needed.
- **Status:** PASS

### Direct loader check

- **Command:** Import `load_candles()` from `backend.main`, print timestamps, select `2026-11-09T14:31:00Z`, and compare it with the expected six-field dictionary.
- **Expected:** Three rows in ascending timestamp order; the 14:31 candle exactly equals `{"timestamp":"2026-11-09T14:31:00Z","open":102,"high":104,"low":100,"close":101,"volume":850}`.
- **Observed:** Timestamps were ordered `14:30`, `14:31`, `14:32`; all six values matched. Timestamp was a string and all five numeric fields were returned as numbers.
- **Status:** PASS

### Live history endpoint

- **URL:** `http://127.0.0.1:8000/api/history`
- **Expected:** HTTP 200 with a timestamp-ordered JSON array using exactly the six requested field names.
- **Observed:** HTTP `200` with three ordered candle objects. The response body was `[{"timestamp":"2026-11-09T14:30:00Z","open":100,"high":103,"low":99,"close":102,"volume":1200},{"timestamp":"2026-11-09T14:31:00Z","open":102,"high":104,"low":100,"close":101,"volume":850},{"timestamp":"2026-11-09T14:32:00Z","open":101,"high":105,"low":101,"close":104,"volume":1500}]`.
- **Status:** PASS

### 14:31 six-field comparison and AutoLoop

- **Cycle 1:** The first PowerShell lookup returned no target because `ConvertFrom-Json` automatically converted the ISO timestamp to a date object. The endpoint body itself was correct.
- **Correction:** Rerun `ConvertFrom-Json -DateKind String` so the timestamp remains the exact JSON string before comparison.
- **Observed checks:** `timestamp=True`, `open=True`, `high=True`, `low=True`, `close=True`, `volume=True`, and `ALL_SIX_MATCH=True`.
- **Status:** PASS after one correction cycle.

### Browser endpoint check

- **Action:** Open `http://127.0.0.1:8000/api/history` in a browser while FastAPI is running.
- **Expected:** The browser visibly shows the three-object JSON array.
- **Observed:** The live endpoint opened and visibly displayed all three ordered candles, including the complete 14:31 object.
- **Status:** PASS

### Remaining history checks

- Larger-timeframe and daily aggregation are not implemented yet; when added, they must aggregate from the one-minute source rows.
- Live provider behavior remains untested because this endpoint intentionally uses synthetic local data.

## 2026-11-11 — Lightweight candlestick and volume chart

### Environment and dependency check

- **Commands:** Read `README.md` and `AGENTS.md`; inspect Windows, `frontend/package.json`, `frontend/package-lock.json`, Node.js, npm, pnpm, direct installed packages, and `npm ls lightweight-charts --depth=0`.
- **Expected:** Identify the working frontend environment and determine whether the chart library is already available before editing dependencies.
- **Observed:** Windows `10.0.26200`, Node.js `25.7.0`, npm `11.10.1`, pnpm `11.25.0`, Vue `3.5.45`, and Vite `8.3.7`. `lightweight-charts` was not installed. `GET /api/history` existed and supplied the three sample rows.
- **Status:** PASS

### Approved chart dependency installation

- **Command:** `npm install --save-exact lightweight-charts@5.2.1` from `frontend/`.
- **Expected:** Install the approved ES-module chart library locally and update only `frontend/package.json`, `frontend/package-lock.json`, and `frontend/node_modules/`.
- **Observed:** `lightweight-charts@5.2.1` and its dependency installed successfully; npm audited 37 packages and reported zero vulnerabilities.
- **Status:** PASS

### Package resolution and production build

- **Commands:** `npm ls lightweight-charts --depth=0`; `npm run build` from `frontend/`.
- **Expected:** Resolve exactly version `5.2.1` and build the Vue frontend.
- **Observed:** npm resolved `lightweight-charts@5.2.1`. Vite transformed 17 modules and completed the production build in 783 ms.
- **Status:** PASS

### Browser chart observation

- **URL:** `http://127.0.0.1:5173/`
- **Expected:** Show distinct adjacent one-minute candles and aligned volume bars from `/api/history`, with data labeled synthetic and inspectable in UTC.
- **Observed:** The chart visibly showed separate candles at `14:30`, `14:31`, and `14:32`, with one color-matched volume bar aligned beneath each candle. The page label read “Synthetic one-minute sample” and the status reported three one-minute UTC candles.
- **Status:** PASS

### 14:31 candle inspection

- **Action:** Use the UTC-minute selector to choose `14:30`, confirm the details change, then return to `14:31`.
- **Expected source values:** November 9, 2026 at `14:31 UTC`; close `101`; volume `850 shares`.
- **Observed:** The selector changed from `14:31` to `14:30`, showing the first row's prices and `1200 shares`, then returned to `14:31`. The final inspector displayed `November 9, 2026`, `14:31 UTC`, open `102`, high `104`, low `100`, close `101`, and volume `850 shares`.
- **Status:** PASS

### TradingView attribution

- **Expected:** Display the TradingView Lightweight Charts attribution notice and link required by the installed library.
- **Observed:** The chart showed its “Charting by TradingView” attribution logo and link. The page also displayed `TradingView Lightweight Charts™ Copyright (с) 2025 TradingView, Inc.` with links to TradingView and the Lightweight Charts documentation.
- **Status:** PASS

### Remaining chart checks

- Real-time updates are not implemented; the chart currently renders the local synthetic history response.
- Larger-timeframe chart aggregation remains untested until the backend aggregation behavior is implemented.

## 2026-11-11 — Yahoo Finance WebSocket probe

### Environment and dependency check

- **Commands:** Read `README.md` and `AGENTS.md`; inspect dependency files, lockfiles, Windows, Python, pip, and yfinance availability in `C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe`.
- **Expected:** Reuse Python 3.13 and determine whether yfinance and its WebSocket clients are available before editing dependencies.
- **Observed:** Python `3.13.17`, pip `26.2.2`, no virtual environment, and no yfinance installation. `backend/requirements.txt` contained only FastAPI and Uvicorn; the frontend manifests were unrelated to this backend dependency.
- **Status:** PASS

### Approved yfinance installation and AutoLoop

- **Command:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m pip install yfinance==1.8.0`.
- **Cycle 1:** pip installed several transitive dependencies but ended before installing the top-level `yfinance` package. `pip show yfinance` found nothing, and no yfinance files or pip process remained.
- **Correction:** Rerun the same approved pinned command from the download cache.
- **Observed:** The retry successfully installed `yfinance-1.8.0` and `curl_cffi-0.17.0`; `python -m pip check` reported `No broken requirements found.` The exact yfinance pin was added to `backend/requirements.txt`.
- **Status:** PASS after one correction cycle.

### Import and client availability

- **Command:** Import yfinance with the selected interpreter and inspect `yf.WebSocket` and `yf.AsyncWebSocket`.
- **Expected:** Version `1.8.0` imports and both documented clients exist.
- **Observed:** `yfinance 1.8.0`; `WebSocket=True`; `AsyncWebSocket=True`.
- **Status:** PASS

### First bounded AAPL subscription and cleanup correction

- **Command:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.yahoo_stream --ticker AAPL --timeout 20`.
- **Expected:** Receive one AAPL update within 20 seconds or report connection-open and receipt-unverified state, then exit promptly.
- **Observed:** The socket opened and the subscription was sent, but no matching update arrived within 20 seconds. The result reported `connection_opened=true` and `receipt_verified=false`. Client shutdown then lingered beyond the receipt timeout.
- **Correction:** Bound listener cancellation and WebSocket close to two seconds each.
- **Status:** Receipt UNVERIFIED; connection PASS; cleanup required one correction cycle.

### Corrected bounded AAPL subscription

- **Command:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.yahoo_stream --ticker AAPL --timeout 8`.
- **Expected:** Preserve the bounded no-message behavior and exit after a short bounded cleanup.
- **Observed:** Exit code `0` after `10.12` seconds. Output: `ticker=AAPL`, `connection_opened=true`, `receipt_verified=false`, `timeout_seconds=8.0`, and `No matching update arrived before the bounded timeout.`
- **Status:** PASS for bounded connection behavior; live receipt remains UNVERIFIED.

### Time and volume interpretation

- **Installed schema:** yfinance 1.8.0 decodes Yahoo's protobuf fields `time` (`sint64`), `day_volume` (`sint64`), and `last_size` (`sint64`).
- **Checker behavior:** A 13-digit `time` is reported as Unix epoch milliseconds; a 10-digit value is reported as Unix epoch seconds. All formatted times are UTC, and backend receipt time uses the local backend clock in UTC.
- **Volume labels:** `day_volume` is labeled as cumulative shares traded during the current market day for an equity and is not one-minute volume. `last_size` is labeled as shares in the most recently reported trade when supplied.
- **Observed:** No live message arrived, so price, source timestamp units, `day_volume`, and `last_size` were not observed and remain unverified for this run.

### Remaining stream check

- Repeat the bounded command when AAPL is actively updating to capture and verify one complete live payload.
- The current probe does not feed received updates into FastAPI or the Vue chart.

## 2026-11-11 — SQLite market observation recorder

### Environment and schema check

- **Command:** Read `AGENTS.md` and `backend/yahoo_stream.py`; import Python's built-in `sqlite3`; inspect existing database files and Git status.
- **Expected:** Reuse the selected Python environment without a dependency change and start with no project database file.
- **Observed:** Python `3.13.17` loaded SQLite runtime `3.50.4`. No SQLite file existed in the project, and no dependency or lockfile change was needed.
- **Status:** PASS

### Disposable database path and command

- **Database:** `C:\Users\Owner\AppData\Local\Packages\sandbox.{ed7c3dfa-b4e4-42f3-90de-3a2f56123c8c}\AC\Temp\live-market-store-16da99749ad744e9a332d99d7a2bc220\recorder-verification.sqlite3`
- **Command:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_market_store --database <database-path>`
- **Input label:** `TEST DATA — constructed recorder verification input` was embedded in every constructed payload.
- **Expected:** The first input creates an observation; its exact repeat reuses that observation but adds another receipt; a changed payload with the same source time remains a separate, non-revision observation.

### Stored observations

- **Observation 1:** `observation_id=1`, ticker `AAPL`, source time `2026-11-11T14:30:00Z`, price `101.0`, `day_volume=1250000`, relationship `new`, `receipt_count=2`, receipt IDs `1..2`.
- **Observation 2:** `observation_id=2`, ticker `AAPL`, the same source time, changed price `101.25`, changed `day_volume=1250850`, relationship `distinct_same_source_time`, `supersedes_observation_id=null`, `receipt_count=1`, receipt ID `3`.
- **Observed:** Both payloads retained their complete canonical source JSON and different SHA-256 hashes. The exact repeat reused observation 1 and was marked `is_exact_repeat=true` on receipt 2.
- **Status:** PASS

### Receipt order and repeat-safe reading

- **Observed receipt rows:** receipt 1 at `14:30:01Z` for observation 1; receipt 2 at `14:30:02Z` for observation 1 with `is_exact_repeat=1`; receipt 3 at `14:30:03Z` for observation 2.
- **Expected reader behavior:** Count rows from `observations` to avoid counting exact repeats twice. Read `receipts` for the full arrival audit trail. Because source time is stored separately from receipt IDs and backend receipt timestamps, late arrivals can be ordered by either source time or actual receipt sequence.
- **Status:** PASS

### Changed messages and identifiable revisions

- **Observed:** The changed same-time test payload had no trusted correction marker, so it was retained beside the earlier value and did not supersede it.
- **Recorder rule:** A caller may set `supersedes_observation_id` only when the feed can identify the correction. The recorder validates matching ticker and source time, inserts a new `revision` row, and preserves the earlier row unchanged.
- **Explicit revision probe:** Recorded price `101.0` as observation 1, then price `101.5` at the same ticker and source time with `supersedes_observation_id=1`. The database retained two rows: `(1, new, null)` and `(2, revision, 1)`.
- **Status:** PASS

### Backend restart persistence

- **Command:** Start a separate Python process with `python -m backend.market_store --database <database-path> --show all` after the writer closed.
- **Expected:** Reopening the database after the backend component restarts returns the same two observations and three receipts.
- **Observed:** `records_survive_restart=true`; the reopened observation and receipt structures matched exactly. The SQLite file size was `28672` bytes.
- **Status:** PASS

### Recorder verification summary

- `two_unique_observations=true`
- `three_receipts=true`
- `repeat_reuses_observation=true`
- `changed_payload_is_retained_separately=true`
- `receipt_order_preserved=true`
- `records_survive_restart=true`

### Remaining recorder check

- No real Yahoo message has arrived yet, so live receiver-to-database persistence remains unverified even though the integrated handler and constructed recorder test pass.

## 2026-11-11 — One-minute observation aggregation

### Environment and dependency check

- **Command:** Read `AGENTS.md`, `backend/market_store.py`, the dependency files, and Git status; compile the aggregation modules with the selected Python interpreter.
- **Expected:** Reuse Python `3.13.17` and built-in `sqlite3`; make no dependency, manifest, lockfile, or environment changes.
- **Observed:** The implementation uses only the standard library and the existing recorder. All three backend modules compiled successfully, and no dependency files changed.
- **Status:** PASS

### Constructed one-minute candle

- **Data label:** `TEST DATA — constructed one-minute candle verification input`
- **Disposable database:** `C:\Users\Owner\AppData\Local\Packages\sandbox.{10b8f9c0-8230-4a86-b2f2-410ac5217e90}\AC\Temp\candle-aggregation-69e2bfbade2e49639b34e0bd9c19072d.sqlite3` (removed after verification).
- **Command:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.check_candle_aggregation --database <disposable-database>`
- **Expected at `2026-11-09T15:00:00Z`:** `open=100`, `high=103`, `low=100`, `close=101`, and `volume=11`.
- **Observed before the minute ended:** The exact expected candle was returned; separate status was `ended=false` at `15:00:55Z`.
- **Observed after the minute ended:** The candle was unchanged; separate status was `ended=true` at `15:01:00Z`.
- **Status:** PASS

### Late source-time ordering

- **Setup:** Store the 14:59:59 baseline, 15:00:05 price, and 15:00:50 price first. Store the 15:00:20 price only after the minute has ended, with backend receipt time `15:01:05Z`.
- **Expected:** Before the late message, high is 101. After recomputation, source-time order places price 103 between the open and close, producing the expected high 103 while close stays 101.
- **Observed:** Before late delivery the candle was `100/101/100/101`, volume 11. After late delivery it was `100/103/100/101`, volume 11.
- **Status:** PASS

### Correction and unknown-volume rules

- **Identifiable correction:** A price 104 revision explicitly superseded the stored price 103 at 15:00:20. The derived candle used high 104; the original remained stored but was excluded from effective observations.
- **Missing baseline:** With no cumulative observation before 15:00, volume was `null`.
- **Session reset:** When cumulative volume fell from the 1000 baseline to 4, volume was `null`.
- **Expected:** Corrections recompute from the effective revision, while indeterminate volume is reported as unknown rather than estimated.
- **Observed:** `identified_correction_replaces_superseded_value=true`, `missing_baseline_volume_is_unknown=true`, and `reset_volume_is_unknown=true`.
- **Status:** PASS

### Aggregation CLI

- **Command:** `python -m backend.candle_aggregation --database <disposable-database> --ticker TEST-NORMAL --as-of 2026-11-09T15:01:00Z`
- **Expected:** Return six-field candles plus a separate minute-status collection.
- **Observed:** The CLI returned the 14:59 candle with unknown volume, the exact expected 15:00 candle with volume 11, and separate `ended=true` entries for both minutes.
- **Status:** PASS

### Remaining aggregation check

- Aggregation is verified against constructed stored observations. It has not yet been exercised with a real Yahoo update because no live message has arrived.

## 2026-11-11 — Exchange-session history timeframes

### Dependency check and approved installation

- **Check:** Python `3.13.17` had pandas `3.1.1` and `zoneinfo`, but neither `exchange_calendars` nor `pandas_market_calendars` was installed.
- **Purpose:** Use maintained XNYS regular-session schedules for holidays, early closes, and UTC changes rather than hard-coded dates.
- **Approved command:** `& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m pip install exchange-calendars==4.13.2`
- **Target:** Existing system Python 3.13 environment; no virtual environment.
- **Files affected:** Added the exact pin to `backend/requirements.txt`; no backend lockfile exists.
- **Observed:** Installed `exchange-calendars 4.13.2` with required helpers `korean_lunar_calendar 0.4.0`, `pyluach 2.3.0`, and `toolz 1.2.0`. `pip check` reported no broken requirements.
- **Status:** PASS after student approval.

### Calendar schedule

- **Command:** Import `exchange_calendars`, load XNYS, and inspect representative sessions.
- **Expected:** Account for seasonal UTC changes and the post-Thanksgiving early close.
- **Observed:** XNYS opened at `13:30Z` on July 6, 2026 and `14:30Z` on November 9, 2026. November 27 opened at `14:30Z` and closed early at `18:00Z`.
- **Status:** PASS

### Supplied five-minute sample

- **Command:** `python -m backend.check_timeframe_history`
- **Data label:** `TEST DATA — constructed timeframe aggregation input` for added rows; the first three source rows came from `prompts/data/sample-candles.csv`.
- **Expected:** The five-minute candle starting `2026-11-09T14:30:00Z` is `open=100`, `high=105`, `low=99`, `close=104`, `volume=3550`.
- **Observed:** Exact match. Status reported 3 available minutes of 5, `coverage_complete=false`, `interval_ended=true`, and `volume_known=true`.
- **Daily coverage:** The supplied rows produced one daily candle with 3 of 390 regular-session minutes, so daily coverage was also incomplete.
- **Status:** PASS

### Session and gap boundaries

- **Constructed 14:35 minute:** `104/106/103/105`, volume 400.
- **Expected:** Start a second five-minute candle at `14:35Z` while remaining in the November 9 daily candle.
- **Observed:** Five-minute timestamps were `14:30Z` and `14:35Z`; daily output remained one candle with 4 of 390 minutes and volume 3950.
- **Constructed next-session minute:** November 10 at `14:30Z`, `106/108/105/107`, volume 500.
- **Expected:** Start a new daily candle.
- **Observed:** Daily timestamps were `2026-11-09T14:30:00Z` and `2026-11-10T14:30:00Z`.
- **Status:** PASS

### Revisions, replay, and volume certainty

- **Revision:** A replacement 14:31 row became available at `15:10Z`. Before that time the five-minute candle retained high 105 and volume 3550. Afterward it used revised high 110 and revised minute volume, producing volume 3600; the 14:32 close remained 104.
- **Replay endpoint:** At `as_of=2026-11-09T14:32:30Z`, only the 14:30 and 14:31 minutes were available. The returned five-minute interval reported 2 of 5 minutes, incomplete coverage, and `interval_ended=false`.
- **Known zero:** A zero-volume minute returned `volume=0` with `volume_known=true`.
- **Unknown volume:** A minute with unknown volume returned `volume=null` with `volume_known=false`.
- **Status:** PASS

### FastAPI HTTP verification and AutoLoop

- **Initial check:** FastAPI's `TestClient` failed before making a request because this Starlette version requires the uninstalled optional `httpx2` package.
- **AutoLoop cycle 1:** Avoided adding an unnecessary test-only dependency and started a real Uvicorn server. The sandbox denied the first localhost socket attempt.
- **AutoLoop cycle 2:** Relaunched Uvicorn with local socket permission and reran the unchanged HTTP assertions.
- **Observed:** `1m`, `5m`, `15m`, `1h`, and `1d` each returned HTTP 200, echoed the requested timeframe, and returned candles with exactly `timestamp,open,high,low,close,volume`. The omitted timeframe defaulted to `1m`; `2m` returned 422 and `MSFT` returned 404.
- **Status:** PASS after two correction cycles. The temporary Uvicorn process was stopped.

### Frontend build and browser SmokeTest

- **Build command:** `npm run build`
- **Observed build:** Vite 8.3.7 transformed 17 modules and completed successfully.
- **Final-check failure:** A later build invocation ran from the repository root and failed because `package.json` is under `frontend/`.
- **AutoLoop correction:** Rerun the unchanged build from `frontend/`; no source correction or dependency change was needed.
- **Corrected result:** Vite again transformed 17 modules and completed successfully.
- **SmokeTest command:** Start Uvicorn on `127.0.0.1:8000`, run `npm run dev` on `127.0.0.1:5173`, and open `http://127.0.0.1:5173/`.
- **Expected:** The Vue client reads the response envelope, draws the default one-minute candles, and supports a real candle-selection operation.
- **Observed:** The page visibly reported `3 1m candles · UTC`. Selecting `14:32 UTC` displayed open 101, high 105, low 101, close 104, and volume 1500 shares. Both services were then stopped.
- **Status:** PASS

### Remaining timeframe check

- The history route still uses the local synthetic AAPL CSV. Exchange-session aggregation has not yet been exercised with one-minute candles generated from a real Yahoo stream.

## 2026-11-11 — Live backend candles in Vue

### Pre-edit trace and dependency check

- **Inspected:** `AGENTS.md`, `docs/design-pipeline.md`, `backend/main.py`, `backend/yahoo_stream.py`, `backend/market_store.py`, both aggregation modules, `frontend/src/main.js`, and `frontend/src/chartAdapter.js`.
- **Observed input/output trace:** Vue fetched only HTTP history and the chart adapter called `setData`; Yahoo dictionaries were stored by `record_message`; one-minute and larger candles were computed only on demand. No event-driven candle updater or FastAPI WebSocket existed.
- **WebSocket stack:** `websockets 17.4`, Starlette `1.10.0`, FastAPI `0.162.3`, and Uvicorn `0.54.0` were already available. No dependency, manifest, or lockfile change was required.
- **Status:** PASS

### Compile and build AutoLoop

- **Initial combined check:** The Vue production build passed, but Python compilation was invoked from `frontend/` and could not resolve relative `backend/*.py` paths.
- **Correction:** Reran the unchanged Python compile from the project root.
- **Observed:** All live backend modules compiled. The final Vite build transformed 17 modules successfully, and `pip check` reported no broken requirements.
- **Status:** PASS after one working-directory correction.

### FastAPI WebSocket integration

- **Server mode:** `MARKET_TEST_FEED=1` with a disposable SQLite database.
- **Input label:** `TEST DATA — recorded interface verification input` was embedded in every replayed source dictionary and sent as the visible source.
- **Command:** Start Uvicorn on port 8014, then run `python -m backend.check_live_candles --url ws://127.0.0.1:8014/ws/candles --database <disposable-database>`.
- **Expected:** Exact six-field candles; contextual symbol/interval/source/feed/completion; in-place 1m updates; next-minute append; backend 5m aggregation; independent upstream disconnect.
- **Observed 15:00 candle:** `open=100`, `high=103`, `low=100`, `close=101`, `volume=11` after three messages with the same minute timestamp.
- **Observed next candle:** `2026-11-09T15:01:00Z`, `102/102/102/102`, volume 4.
- **Observed 5m candle:** `2026-11-09T15:00:00Z`, `100/103/100/102`, volume 15.
- **Message contract:** Every `candle` contained exactly `timestamp,open,high,low,close,volume`; every message carried AAPL, selected interval, labeled source, feed status, and completion metadata.
- **Disconnect check:** The upstream status changed to `disconnected` while the client successfully pinged the still-open FastAPI WebSocket.
- **Invalid quantities:** Zero and fractional quantities were each stored as rejected orders with explanatory reasons.
- **Status:** All eleven assertions PASS.

### Stored-row comparison

- **Stored row:** Observation 4, AAPL, source time `2026-11-09T15:00:50Z`, price 101, cumulative volume 1011.
- **Displayed/streamed candle:** The corresponding 15:00 candle closed at 101 and had minute volume 11, calculated from the 1000 pre-minute baseline.
- **Audit result:** Five unique test observations remained stored. Replaying them for the second timeframe retained 10 receipts without duplicating observations in the integration check; the browser run across three timeframes retained 15 receipts.
- **Status:** PASS

### Browser SmokeTest with recorded input

- **Command:** Start Uvicorn with `MARKET_TEST_FEED=1`, start Vite, and open `http://127.0.0.1:5173/`.
- **Default 1m observation:** The page displayed AAPL, interval `1m`, source `TEST DATA — recorded interface verification input`, a changing source age, `Upstream feed: disconnected`, `FastAPI socket: connected`, and `Candle: Still forming`.
- **1m candle comparison:** Selecting `2026-11-09T15:00:00Z` visibly showed open 100, high 103, low 100, close 101, and volume 11 shares. The next 15:01 candle appeared separately with price 102 and volume 4.
- **5m user operation:** Selecting `5 minutes` reloaded history, replaced the WebSocket subscription, and visibly showed a 15:00 candle with open 100, high 103, low 100, close 102, and volume 15.
- **Daily user operation:** Selecting `Daily` reloaded one `1d` candle and retained the visible `Still forming` state and separate disconnected-upstream/connected-FastAPI statuses.
- **Status:** PASS. Both services were stopped and the disposable browser database was removed.

### Actual Yahoo observation

- **Bounded command:** `python -m backend.yahoo_stream --ticker AAPL --timeout 8 --database <disposable-database>`.
- **Observed:** A real AAPL message arrived and was stored as observation 1: price `356.05`, source time `2026-11-12T00:55:02Z`, backend receipt `2026-11-12T00:55:01.986905Z`. Yahoo supplied no `day_volume` or `last_size` in that message.
- **Regular-session result:** The source time was outside XNYS regular hours, so the backend correctly did not create a regular-session candle from it.
- **Production browser attempt:** The dashboard showed source `Yahoo Finance`, upstream `connected`, FastAPI socket `connected`, and the three historical candles. No actual observation arrived during a subsequent visible 16-second check, so it continued to show `No live observation yet`.
- **Status:** Real receipt/storage PASS; actual stored-record-to-regular-session-candle browser comparison PENDING. No live values were substituted with test data.

### Cleanup and remaining check

- All verification services were stopped.
- The recorded-input, production-dashboard, final-regression, and bounded-Yahoo disposable SQLite databases were removed; no verification database was retained in the project.
- Repeat the production browser check during XNYS regular trading hours to compare a real stored observation, aggregated candle, and visible chart values end to end.

## 2026-11-12 — Offline recorded-session Replay

### Existing path and dependency check

- **Inspected:** `AGENTS.md`, `backend/market_store.py`, `backend/candle_aggregation.py`, `backend/timeframe_history.py`, `backend/live_candles.py`, `backend/main.py`, `frontend/src/main.js`, `frontend/src/chartAdapter.js`, dependency manifests, lockfiles, and Git status.
- **Existing path:** `observations` stores canonical source messages and revision links; `receipts` supplies monotonic arrival order; the candle functions derive one-minute and selected-timeframe values; the Vue chart adapter replaces equal timestamps or appends new intervals.
- **Environment:** Python 3.13.17 with built-in SQLite 3.50.4; the installed `websockets 17.4`, FastAPI, Uvicorn, Vue, Vite, and Lightweight Charts packages were sufficient.
- **Dependency result:** No installation or dependency-file change was required.
- **Data availability:** No retained live-session SQLite file existed in the project, so verification used a separate ignored database labeled `TEST DATA — recorded session replay verification input`. An actual captured regular-session replay remains pending.

### Deterministic read-only engine check

- **Command:** `python -m backend.check_replay_session --database backend/replay-test.sqlite3 --create-test-session` for first creation; subsequent runs omit `--create-test-session`.
- **Selection:** AAPL, source-time range `2026-11-09T14:59:00Z` through `2026-11-09T15:01:00Z`, one-minute timeframe.
- **Constructed arrival order:** baseline at 14:59:59; 15:00:05 price 100; 15:00:50 price 101; late 15:00:20 price 103 arriving at 15:01:05; identifiable 15:00:50 revision price 102/cumulative volume 1012 arriving at 15:01:10.
- **Expected final 15:00 candle:** open 100, high 103, low 100, close 102, volume 12.
- **Observed:** Exact match. Receipt order was 1–5; preserved source times made the late high and revision appear only at their recorded receipt points. Both replay runs returned identical results.
- **Read-only result:** Source observation count was 5 before and after both runs. The engine opens the source with SQLite `mode=ro` and reconstructs state in `MarketRecorder(":memory:")`.
- **Empty range:** The next-day range returned no events and the required message contract.
- **Status:** All nine engine assertions PASS.

### FastAPI replay WebSocket with live feed off

- **Backend command:** Set `MARKET_LIVE_FEED=0`, point `MARKET_DATABASE` at `backend/replay-test.sqlite3`, then run `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`.
- **Verifier command:** `python -m backend.check_replay_websocket`.
- **Expected:** Live-feed flag false; `replay_started`, five ordered `replay_observation` messages, then `replay_complete`; close 102 and volume 12; repeatable result; unchanged count; empty selection message.
- **Observed:** Every assertion passed. `/api/replay/selections` reported `live_feed_enabled=false`, read-only Replay, AAPL, five observations/five receipts. Both WebSocket runs returned the expected final candle and count 5 before/after. The empty range returned `This selection has no recorded observations.`
- **Status:** PASS.

### Frontend build and browser SmokeTest

- **Build command:** Run `npm run build` from `frontend/`.
- **Observed:** Vite 8.3.7 transformed 17 modules and completed successfully.
- **SmokeTest:** Start Uvicorn in the offline mode above, run `npm run dev -- --host 127.0.0.1 --port 5173`, open the dashboard, switch Mode to Replay, retain AAPL and the selected UTC range, and press Start Replay.
- **First visible run:** The page was labeled `AAPL Replay` and the chart banner said `Replay`. It showed source `Recorded SQLite session`, upstream feed `disconnected`, final source observation `November 9, 2026 15:00:50 UTC`, original receipt time `2026-11-09T15:01:10Z`, and `5 observations before, 5 after`.
- **Visible candle comparison:** The selected 15:00 UTC candle showed open 100, high 103, low 100, close 102, and volume 12 shares, matching the SQLite-derived expectation.
- **Second visible run:** Pressing Start Replay again produced the same close 102 and volume 12, stored observation count 5, and unchanged before/after count.
- **Empty-range behavior:** The backend WebSocket and Vue handler use the exact message `This selection has no recorded observations.` The WebSocket path was exercised successfully; direct entry into the browser's native `datetime-local` field could not be automated by the browser driver, so that particular visible empty-message operation remains unrun.
- **Status:** Build PASS; two-run browser values/read-only state PASS; browser entry of an empty native date field PENDING.

### AutoLoop and cleanup

- **Cycle 1:** The combined engine check attempted to create an already-existing disposable test database and correctly stopped with `FileExistsError`. Reran the same assertions without the creation flag; all passed without source edits.
- **Cycle 2:** Initial local services inside the restricted sandbox could not bind/access localhost. Restarted Uvicorn and Vite with local-socket permission and reran the unchanged integration checks; all passed.
- **Cycle 3:** The first browser repeatability extraction used an ambiguous `main` locator because both the Vue mount point and page content are `main` elements. Narrowed it to `main.market-shell` and reran; all eight visible assertions passed.
- **Cleanup:** Services were stopped after verification and the ignored test database was removed.

## 2026-11-12 — Extensible named indicators

### Inspection and dependency check

- **Inspected:** `AGENTS.md`, Git status, backend history/aggregation/storage modules, FastAPI routes, Vue dashboard, Lightweight Charts adapter, manifests, and lockfiles.
- **SMA finding:** No SMA implementation or indicator abstraction existed in the inspected working tree. SMA was added as the first calculation in the new shared interface rather than maintaining a separate code path.
- **Runtime:** Windows, Python 3.13.17, SQLite 3.50.4, FastAPI 0.162.3, Uvicorn 0.54.0, Node 25.7.0, and npm 11.10.1.
- **Dependencies:** Built-in `sqlite3` and the already installed backend/frontend packages covered the task. No install, manifest, or lockfile change was required.

### Calculation contract and fixture

- **Data label:** `TEST DATA — indicator extension verification fixture`.
- **Fixture:** Three one-minute candles with high/low pairs `(12,9)`, `(15,10)`, and `(13,11)` in `prompts/data/indicator-fixture.csv`.
- **Inputs:** Ordered six-field candles, separate `interval_ended` flags, and validated per-instance settings. Only completed candles enter a window.
- **Output:** One `{timestamp, value}` item for every candle time. `value=null` represents a warm-up gap or incomplete candle; numeric outputs use the type's declared units.
- **SMA:** Close prices in price units; SMA 2 observed `[null, 12.5, 13.0]`.
- **Rolling range:** High/low prices; highest high minus lowest low in price-difference units.

### Python calculation and SQLite restart check

- **Command:** `python -m backend.check_indicators --database backend/indicator-test.sqlite3` against a new disposable database.
- **Expected Range 2:** `[null, 6, 5]`.
- **Observed Range 2:** `[null, 6.0, 5.0]`.
- **Expected Range 3:** `[null, null, 6]`.
- **Observed Range 3:** `[null, null, 6.0]`.
- **Persistence:** After closing and reopening SQLite, the rows remained `Range 2` with `{"window":2}` and `Range 3` with `{"window":3}`.
- **Validation:** Window zero returned `Window must be at least 1 completed candle.` and the two valid rows remained.
- **Status:** All eight assertions PASS.

### FastAPI and browser SmokeTest

- **Backend fixture command:** Set `MARKET_LIVE_FEED=0`, `MARKET_DATABASE=backend/indicator-browser.sqlite3`, and `MARKET_CANDLE_FILE=prompts/data/indicator-fixture.csv`, then start Uvicorn on port 8000.
- **Frontend command:** Run `npm run dev` from `frontend/` and open `http://127.0.0.1:5173/`.
- **User operations:** In Vue, choose Rolling price range; create `Range 2` with window 2 and `Range 3` with window 3.
- **Third-candle expected:** Range 2 = 5; Range 3 = 6.
- **Third-candle observed:** Inspector visibly showed `5 price difference` and `6 price difference` at `2026-11-09T14:32:00Z`.
- **Refresh:** After a full page reload, Vue reported `2 saved for AAPL 1m`; both named configuration cards returned with windows 2 and 3, and both third-candle values remained 5 and 6.
- **Invalid operation:** Submitted `Invalid zero` with rolling-range window 0. The page visibly explained `Window must be at least 1 completed candle.` while continuing to show two saved indicators and their valid values.
- **SQLite comparison:** Direct query returned exactly two rows: `Range 2`, `price_range`, `{"window":2}` and `Range 3`, `price_range`, `{"window":3}`.
- **Frontend build:** `npm run build` transformed 17 modules and completed successfully.
- **Status:** PASS.

### AutoLoop and cleanup

- **Cycle 1 failure:** The first browser load received HTTP 500 from `GET /api/indicators`. The SQLite connection had been created on the application thread and Python rejected its use in FastAPI's sync worker thread.
- **Narrow correction:** Opened only the indicator SQLite connection with `check_same_thread=False` and serialized access with a re-entrant lock. Restarted FastAPI and reran the unchanged browser check.
- **Corrected result:** All creation, calculation, refresh-persistence, invalid-window, and direct-SQLite checks passed.
- **Cleanup:** Verification services were stopped and both ignored disposable indicator databases plus their WAL/SHM files were removed.

## 2026-11-12 — Long-only paper account

### Inspection and dependency check

- **Inspected:** `README.md`, `AGENTS.md`, Git status, the observation/receipt schema, live Yahoo callback, replay arrival loop, FastAPI application, Vue dashboard, manifests, and lockfiles.
- **Existing implementation:** No paper account, order, fill, cash, or position code existed.
- **Runtime:** Python 3.13.17 with SQLite 3.50.4, FastAPI 0.162.3, Uvicorn 0.54.0, Node 25.7.0, and npm 11.10.1.
- **Dependencies:** Python `sqlite3` and the existing application packages covered the task. No dependency installation or manifest/lockfile change was required.

### Fill rule and persistence design

- **Rule:** Accepted orders remain pending and fill at the next eligible observed price after submission, rounded to cents, with zero fees.
- **Eligibility:** Submission records the latest `paper_market_events.market_event_id`. Only a later event for the symbol is eligible. Live, replay, and labeled fixture arrivals share this path, so replay cannot use future observations.
- **Atomicity:** The fill row, account cash, position quantity, and order status update inside one SQLite transaction after cash/shares are rechecked.
- **Traceability:** Orders retain request ID, order ID, symbol, action, side, quantity, submission time, status, and rejection reason. Fills retain order ID, price, observation ID, receipt ID, market-event ID, and execution time.
- **Idempotency:** `paper_orders.request_id` is unique. Reusing it returns the existing order and cannot insert another order or fill.
- **Shared entry point:** Vue and a future decision agent both use `execute_paper_action`.

### Python transaction and restart check

- **Command:** `python -m backend.check_paper_account --database backend/paper-core-test.sqlite3` using a new disposable path.
- **Data label:** `TEST DATA — paper account execution fixture`.
- **Expected/observed buy:** Buy 4 filled at $100; cash $600, shares 4.
- **Expected/observed partial sell:** Sell 1 filled at $110; cash $710, shares 3.
- **Expected/observed close:** Sell remaining 3 at $105; cash $1,025, shares 0.
- **Retry:** Reused the buy request ID; result was `idempotent_replay` with no duplicate.
- **Empty sale:** Sell 1 from zero shares was rejected.
- **Hold/wait:** Both returned `no_order` and did not change order count.
- **Restart:** Reopened the database with a different requested starting balance; persisted cash remained $1,025, shares 0, and fill count exactly 3.
- **Status:** All nine assertions PASS.

### Browser SmokeTest and SQLite comparison

- **Fixture:** FastAPI ran with `MARKET_LIVE_FEED=0`, `MARKET_PAPER_FIXTURE=1`, `PAPER_STARTING_CASH=1000`, and `MARKET_DATABASE=backend/paper-browser.sqlite3`. Vue ran on port 5173.
- **Initial dashboard:** Cash $1,000.00, shares 0, orders 0, and a visibly labeled fixture-price control.
- **Buy operation:** Submitted buy 4. It visibly remained pending before price arrival. Supplying $100 produced cash $600.00, shares 4, and fill linked to observation 1.
- **Partial sell:** Submitted sell 1 then supplied $110. Dashboard showed cash $710.00, shares 3, and fill linked to observation 2.
- **Close:** Submitted close then supplied $105. Dashboard showed cash $1,025.00, shares 0, and fill linked to observation 3.
- **Stable retry:** Retried the completed close request with the same request ID. Vue showed `Existing order returned; no duplicate order or fill was created.` Order count remained 3.
- **Rejection:** With a new request ID, sell 1 from the empty position was rejected with `Cannot sell 1 shares; position holds 0.` Order count became 4 while fill count stayed 3.
- **Hold/wait:** Browser operations showed their explanatory messages and kept order count 4, cash $1,025, and shares 0.
- **Backend restart:** After stopping and restarting FastAPI against the same file, the reloaded dashboard returned cash $1,025.00, shares 0, four orders, the rejection, and all three fill prices.
- **Direct SQLite:** `paper_accounts.cash_cents=102500`; AAPL position quantity 0; four order rows (three filled, one rejected); exactly three fill rows at 10000, 11000, and 10500 cents linked to observations/receipts/events 1, 2, and 3.
- **Frontend build:** Vite transformed 17 modules and completed successfully.
- **Status:** PASS.

### AutoLoop and cleanup

- **Cycle 1 failure:** After submitting the first pending buy, the fixture-price control disappeared. The order response returned the account snapshot without the `fixture_enabled` flag used by Vue.
- **Narrow correction:** Routed every paper-account response through one `paper_snapshot` helper that consistently carries the fixture flag. Restarted FastAPI without deleting the database; the pending order persisted and the unchanged test continued.
- **Corrected result:** The complete sequence, stable retry, rejection, hold/wait, restart, and SQLite comparison passed.
- **Cleanup:** Both services were stopped and the ignored disposable paper databases plus WAL/SHM files were removed.

## 2026-11-12 — Paper account P&L history

### Inspection and dependency check

- **Inspected:** `AGENTS.md`, Git status, `backend/paper_trading.py`, FastAPI paper routes, the live candle receiver, Vue paper-account panel, existing paper checks, manifests, and lockfiles.
- **Existing path:** Cash, positions, orders, fills, stored observations, and receipt links already shared one SQLite database. No cost basis or P&L ledger existed.
- **Dependencies:** Python's built-in `sqlite3`, existing FastAPI/Vue packages, and the existing runtimes were sufficient. No installation, manifest, or lockfile change was required.

### Calculation and idempotency rules

- **Weighted average:** Buys add fill cost to `cost_basis_cents`. A partial sale removes its proportional weighted basis, records proceeds minus removed basis as realized P&L, and leaves the remaining average unchanged. A close removes all remaining basis.
- **Valuation:** A fill row uses its fill price. A completed one-minute candle records a new row for an open position with its close, event time, source, and observation/receipt links.
- **Values:** Each append-only row snapshots cash, shares, average cost, cumulative realized P&L, unrealized P&L, and total P&L. An open position without a usable basis/price is returned as `valuation_available=false` and Vue displays `Unavailable`, never a known zero.
- **Idempotency:** `UNIQUE(account_id, symbol, event_key)` plus `ON CONFLICT DO NOTHING` preserves one row when the same fill or candle event is reprocessed. Live and Replay completed-candle keys include symbol, timeframe, candle start, and close cents, so unchanged recomputation is one event while a late close revision is retained as a new valuation.

### Disposable SQLite fixture and restart

- **Command:** `python -m backend.check_pnl_history --database backend/data/pnl-check.sqlite3` against a new disposable database.
- **Data label:** `TEST DATA — P&L history fixture`.
- **Expected/observed rows:** buy 4 at $100 = cash $600, shares 4, realized $0, unrealized $0, total $0; value at $110 = $0/$40/$40; sell 1 at $110 = cash $710, shares 3, $10/$30/$40; value at $95 = $10/-$15/-$5; close 3 at $105 = cash $1,025, shares 0, $25/$0/$25.
- **Repeat:** The $110 completed-candle event was submitted twice with the same stable key; direct SQLite contained one row for it and five P&L rows total.
- **Restart:** Closing and reopening `PaperAccount` returned the identical five API rows. Direct SQLite after restart still returned five rows with the expected cent values.
- **Status:** All six fixture assertions PASS.
- **Final regression after live/Replay key review:** Python compilation passed and the same fixture again reported `amounts_match=true`, `repeat_event_is_single_row=true`, and `restart_preserves_rows=true`.

### Browser SmokeTest and direct SQLite comparison

- **Services:** FastAPI ran with `MARKET_DATABASE=backend/data/pnl-check.sqlite3`, `PAPER_STARTING_CASH=1000`, `MARKET_LIVE_FEED=0`, and `MARKET_PAPER_FIXTURE=1`; Vite served `http://127.0.0.1:5173/`.
- **Visible table before restart:** Vue showed five rows in order: fill $100; completed candle $110; fill $110; completed candle $95; fill $105. Visible cash/share/P&L cells matched the five expected states. The summary showed cash $1,025.00, shares 0, realized $25.00, unrealized $0.00, and total $25.00.
- **Direct query before restart:** Returned the same five cent rows: `(60000,4,0,0,0)`, `(60000,4,0,4000,4000)`, `(71000,3,1000,3000,4000)`, `(71000,3,1000,-1500,-500)`, `(102500,0,2500,0,2500)`.
- **Backend restart:** Uvicorn was stopped and restarted against the same SQLite path. Reloading the page visibly restored all five rows and the same $1,025 / $25 summary.
- **Direct query after restart:** Count remained 5 and every cent value matched the pre-restart query.
- **Frontend build:** `npm run build` transformed 17 modules and completed successfully.
- **Status:** Browser, SQLite, and restart comparisons PASS with no discrepancy.

### AutoLoop

- **Cycle 1 failure:** The first paper regression command was launched from `frontend/`, so Python could not resolve the `backend` package and returned `ModuleNotFoundError`.
- **Narrow correction:** Reran the unchanged command from the documented project root. All eleven existing paper-account assertions passed, and Python compilation passed for the P&L, FastAPI, and live-candle modules.
- **Localhost launch:** The restricted launch could not expose localhost to the browser. Restarted Uvicorn and Vite with approved local-socket permission; the unchanged browser check passed.
- **Cleanup command correction:** The first cleanup-path inspection was launched from `frontend/` and could not resolve `backend/data`. Reran it from the project root, verified every absolute target stayed under the workspace, then removed the disposable database, WAL, SHM, and regression database. None remains.

## 2026-11-12 — Frozen chart decision analysis

### CHECK

- **Inspected:** `AGENTS.md`, Git status, `backend/main.py`, the SQLite indicator and paper-account stores, `frontend/src/main.js`, `frontend/src/chartAdapter.js`, manifests, and lockfiles. The requested `POST /api/decisions` route did not yet exist, so the route and its local persistence were added as the smallest required foundation.
- **Runtime:** Windows, Python `3.13.17`, SQLite `3.50.4`, Node.js `25.7.0`, npm `11.10.1`, Vue `3.5.45`, Vite `8.3.7`, and Lightweight Charts `5.2.1`.
- **Dependencies:** Existing Python standard-library HTTP, image-header, hashing, JSON, and SQLite support plus the installed frontend packages covered the task. No package installation or manifest/lockfile change was required.
- **Provider contract:** The official OpenAI Decisions API documentation confirms `POST /v1/decisions`, named choice questions, and a single user message containing text, image, and JSON inputs. The implementation sends `input_text`, the full `data:image/png;base64,...` value as `input_image.image_url`, and the frozen snapshot as `input_json.data`, using `gpt-6-luna`.

### Snapshot and build checks

- **Command:** `python -m backend.check_decision_snapshot --database backend/data/decision-smoke.sqlite3 --captures backend/data/decision-captures-smoke`
- **Expected:** A labeled three-candle fixture ends at `2026-11-09T14:32:00Z`, persists a flat paper position with zero orders, and calculates a downward crossover from Fast SMA 1 and Slow SMA 2.
- **Observed:** All six assertions passed. At the prior candle Fast/Slow were `14/12.5`; at the cutoff they were `12/13`, so Python reported `downward`. Cash was `$1,000`, shares were `0`, and order count was `0`.
- **Command:** `npm run build` in `frontend/`.
- **Expected:** The chart capture and decision UI resolve the existing packages and build.
- **Observed:** Vite built 17 modules successfully.
- **Command:** Compile the changed backend modules with the selected Python interpreter and run `git diff --check`.
- **Expected:** No syntax or whitespace errors.
- **Observed:** Both checks passed when run from the project root.

### Browser SmokeTest with provider test double

- **Fixture:** `TEST DATA — recorded downward crossover decision fixture`. The backend used `backend/data/decision-smoke.sqlite3`, `prompts/data/indicator-fixture.csv`, `MARKET_LIVE_FEED=0`, `DECISION_PROVIDER=test`, and `OPENAI_BASE_URL=http://127.0.0.1:8011/v1`. The local provider double listened on port 8011, FastAPI on 8000, and Vue on 5173.
- **User operation:** Opened the dashboard, selected the completed `14:32 UTC` AAPL one-minute candle, and clicked **Ask about chart**.
- **Visible result:** Vue retained a chart-only PNG preview containing three candlesticks, aligned volume, Fast SMA, and Slow SMA. The panel showed the snapshot ID, AAPL, `1m`, range `14:30–14:32 UTC`, cutoff `14:32 UTC`, Python crossover `downward`, and provider answers `action=wait`, `crossover=downward`, `evidence=sufficient`.
- **Comparison:** The visible and Python crossover claims both reported `downward`. The result was marked consistent and advisory. The UI reported paper orders unchanged.
- **Provider observation:** The double received one user message with part types `input_text`, `input_image`, and `input_json`, and named questions `action`, `crossover`, and `evidence`. It decoded a `1008x660` PNG.
- **Persistence comparison:** Decision `dec_f52b6961de3b40eabb0cb60fae33e78b` referenced snapshot `snap_298eb99865864f8db9f45b89beeb40a3`. The provider payload, SQLite decision record, and saved PNG all had SHA-256 `b2d6e9eaa22816a70ef6903e5ab59e16a4296e1065797163bd3d8e8e7fdbc594`. Direct SQLite showed zero paper orders and one saved decision.
- **Advisory safeguard:** The action button called snapshot and decision routes only. It did not call `execute_paper_action`, and the order count remained zero.

### Rejection and eligibility checks

- **Unreadable image:** A matching snapshot with an invalid PNG data URL returned HTTP `422` with `The chart image is not a readable PNG; recapture the chart.`
- **Mismatched snapshot:** A request whose interval differed from the stored snapshot returned HTTP `422` with `The chart metadata does not match the saved snapshot; recapture the chart.`
- **Named-answer validation:** Direct checks confirmed a missing `action`, `crossover=unreadable`, and `crossover=upward` against Python's `downward` each produce an ineligible result with a specific reason. Valid named answers remained eligible for advisory display.

### Live provider check

- **Environment inspection:** `OPENAI_API_KEY` and `OPENAI_BASE_URL` were absent. No credential was written to code, prompts, logs, or Git.
- **Observed:** An authenticated live image request could not be exercised. No model answers were invented or copied from the test double. This check remains pending until the student supplies `OPENAI_API_KEY` through the process environment and starts the backend with `DECISION_PROVIDER=openai`.

### AutoLoop and shutdown

- **Cycle 1 failure:** A combined command invoked Python compilation from `frontend/`, so relative `backend/*.py` paths were not found. The independent Vue build still passed.
- **Narrow correction:** Reran the same compilation from the documented project root without changing source; compilation passed. The capture adapter was then protected with `try/finally` so live chart data is restored even if image export fails, and the final build was rerun.
- **Shutdown:** Stopped the Vue, FastAPI, and local provider-double processes after the browser and HTTP checks.
- **Final checks:** After adding failure-safe chart restoration, Python compilation passed and `npm run build` again built 17 modules successfully. `git diff --check` reported no whitespace errors; the remaining messages were Windows LF-to-CRLF notices only.
- **Cleanup attempt:** The first PowerShell artifact-list command placed a pipe directly after `foreach` and failed with an empty-pipe parser error before changing any files.
- **Cleanup correction:** Collected the rows into an array, confirmed the database, WAL, SHM, and capture directory resolved beneath the project root, then removed those four disposable test artifacts with `Remove-Item -LiteralPath`. A follow-up check reported `Disposable decision artifacts removed.`

### Authenticated live image check (later on 2026-11-12)

- **Credential location:** The student placed `OPENAI_API_KEY` in the ignored project-root `.env`. Its assignment was checked for presence only; the value was loaded into the backend process environment without printing it. No user or machine environment variable was present. `.env` is ignored by Git.
- **Fixture command:** `python -m backend.check_decision_snapshot --database backend/data/decision-live-check.sqlite3 --captures backend/data/decision-captures-live-check`. All six fixture assertions passed for `TEST DATA — recorded downward crossover decision fixture`.
- **Services:** FastAPI ran on `127.0.0.1:8000` with `DECISION_PROVIDER=openai`, `OPENAI_BASE_URL=https://api.openai.com/v1`, `MARKET_DATABASE=backend/data/decision-live-check.sqlite3`, `DECISION_CAPTURE_DIR=backend/data/decision-captures-live-check`, `MARKET_CANDLE_FILE=prompts/data/indicator-fixture.csv`, and `MARKET_LIVE_FEED=0`. Vue ran on `127.0.0.1:5173`. The credential came only from the ignored `.env`; the exact key was never written in the command or output.
- **Initial launch failure:** Services launched inside the socket sandbox could not be reached (`ERR_CONNECTION_TIMED_OUT`; local HTTP reported socket access forbidden). Stopped both and relaunched with network permission. Both then served the browser check.
- **Browser operation:** Opened `http://127.0.0.1:5173/`, confirmed the selected completed AAPL `1m` candle at `2026-11-09T14:32:00Z`, and clicked **Ask about chart** once. The chart preview froze the range `14:30–14:32 UTC` and Python crossover `downward`.
- **Actual provider answers:** OpenAI `gpt-6-luna` returned `action=wait`, `crossover=downward`, and `evidence=sufficient`. The dashboard displayed those three answers, compared visual `downward` to Python `downward`, marked the answers internally consistent, and displayed `Paper orders unchanged: yes`. These are actual model answers, separate from the earlier test double.
- **SQLite comparison command:** Query `decision_records` and `decision_snapshots` in `backend/data/decision-live-check.sqlite3`, hash the saved PNG, and count `paper_orders` and `decision_records`.
- **Expected:** One persisted decision, matching preview cutoff and crossover, identical recorded/file PNG hashes, zero paper orders.
- **Observed:** Decision `dec_22a33c78a4024f63bf9e2f0d7d8cf83c`, snapshot `snap_0eddb095f9e64074b584ab2f34ffedd5`, provider `openai`, model `gpt-6-luna`; the three persisted named choices matched the browser. The saved 79,299-byte PNG and database hash both equaled `df3064764278b3b8a595b8d1b9e2c00c26847e5af8b1436601a65f101ea60391`. One decision and zero paper orders persisted; eligibility was true with no conflict reasons.
- **Scope:** This is a live OpenAI image request using labeled synthetic market data. It does not establish live Yahoo feed accuracy or trading performance.
- **Other observation:** The backend log showed the candle WebSocket handshake returned HTTP `403`, so the dashboard feed status said FastAPI socket disconnected. History, indicator, paper, snapshot, and decision HTTP requests succeeded, including `POST /api/decisions` HTTP `201`. The WebSocket status issue is separate from this frozen history image check and remains to investigate.
- **Shutdown:** Stopped FastAPI and Vite after the live check. Retained the ignored disposable database and PNG capture as local evidence for the decision ID; no credential was stored in either artifact.

## 2026-11-12 — Analyst and reviewer decision gate

- **CHECK:** Read `AGENTS.md`, inspected Git status, `backend/main.py`, `backend/decisions.py`, the SQLite schema, Vue decision panel, backend/frontend manifests and lockfile. Reused Python 3.13.17, Node 25.7.0, npm 11.10.1, FastAPI, and Lightweight Charts. No dependency installation or manifest change was required. The existing route made one Decisions call and stored one set of answers.
- **Flow:** Vue sends the selected completed candle's saved snapshot ID and frozen PNG to `POST /api/decisions`. Python loads that immutable snapshot. An analyst call asks the three existing named choices. The reviewer call receives the exact same image and snapshot plus those actual analyst answers and backend facts, and answers a separate named `verdict` choice. Each call has its own timeout; malformed or failed calls are saved as ineligible. Python independently checks cash, one-share price, shares, and SMA crossover; reviewer acceptance cannot override a failed rule. The route never invokes paper execution.
- **Schema:** Existing `decision_records` gains reviewer model, named answers, question, final check, and role-error columns through additive migration. Prior saved decisions remain readable. Both role outputs and the snapshot ID share one decision row.
- **Fixed-reply command:** `python -m backend.check_decision_review` against a new `backend/data/decision-review-test.sqlite3`; labeled `TEST DATA — fixed analyst/reviewer replies`. Expected two calls with identical image and snapshot per case, persisted replies, and zero orders.
- **Agreed case:** Upward crossover; analyst `buy`, reviewer `accept`, cash `$1,000`, one-share price `$13`. Observed eligible `true`, saved decision `dec_5f7e08fb6c1a49da8abf0f37fa789353`, zero orders.
- **Reviewer rejection:** Same facts and analyst `buy`; reviewer `reject_unsupported_signal`. Observed eligible `false`, saved decision `dec_a9c2a0ff07094a4187f0d83b00d65cf8`, zero orders. Python facts remained visible despite the reviewer verdict.
- **Unaffordable acceptance:** Upward crossover; cash `$5`, price `$13`; analyst `buy`, reviewer `accept`. Python rejected with `Cash 5.0 is below one share at 13.` Observed eligible `false`, saved decision `dec_f8319285ace84f96b3396ffd5c54f964`, zero orders.
- **Failure replies:** A simulated analyst timeout made one call and saved an ineligible decision without calling the reviewer. An invalid reviewer response made two calls and saved an ineligible decision. Both checks passed in the same disposable fixture.
- **Persistence:** The check compared each returned analyst answer, reviewer answer, and final check with direct SQLite JSON and confirmed the same snapshot was passed to both roles. All assertions passed. A prior disposable run was removed after resolving each target beneath the workspace, then the final check was rerun successfully.
- **Live setup:** Loaded `OPENAI_API_KEY` from the ignored root `.env` into the FastAPI process without printing it. Used the retained labeled downward-crossover database `backend/data/decision-live-check.sqlite3`, `MARKET_LIVE_FEED=0`, the indicator fixture CSV, `DECISION_PROVIDER=openai`, and the existing capture directory. FastAPI served port 8000 and Vite port 5173 with network permission.
- **Live browser operation:** At completed AAPL `1m` candle `2026-11-09T14:32:00Z`, clicked **Ask about chart** once. Snapshot `snap_14ef600772994996b3a9aae5ea5481e3` froze three candles, both SMA lines, a downward Python crossover, `$1,000` cash, and zero shares. Both calls used `gpt-6-luna`.
- **Actual model outputs:** Analyst `action=wait`, `crossover=downward`, `evidence=sufficient`; reviewer `verdict=reject_unsupported_signal`. The browser displayed the two roles, facts (`$1,000` cash, `$12` one-share price, zero shares, downward crossover), and ineligible final result. This was a reviewer rejection, not a cash failure. Zero orders were created.
- **Direct SQLite comparison:** Decision `dec_1733d936be7f4e0989a8ddcff148f1e6` stores those exact analyst/reviewer choices, model names, snapshot ID, backend facts, reviewer rejection, and `eligible_for_automation=0`; `SELECT COUNT(*) FROM paper_orders` returned `0`. The old decision row remained intact after migration.
- **Build checks:** Python compilation for `backend/decisions.py`, `backend/main.py`, and `backend/check_decision_review.py` passed; final Vite build built 17 modules; `git diff --check` had no whitespace errors (only Windows line-ending notices).
- **Shutdown and remaining issue:** Stopped FastAPI and Vite after the live request. The forced timeout and invalid reviewer reply were checked with fixed responses, not over external HTTP. The live candle WebSocket still reported disconnected; the recorded-history HTTP decision path succeeded.

## 2026-11-12 — Reviewed decision to paper automation

- **CHECK:** Read `AGENTS.md`, inspected Git status, the decision snapshot/analyst/reviewer route, `PaperAccount.submit`, `process_market_observation`, cash/position/fill/P&L schema, Vue chart capture and completion handling, Python/Node versions, manifests and lockfile. Reused Python 3.13.17, existing FastAPI and Vue packages, and SQLite; no installation or dependency-file change.
- **Trace before edit:** A completed candle and chart PNG produced a saved decision with one snapshot ID, analyst named answers, reviewer verdict, and Python final facts. A separate paper order used `submit` to remain pending until a later `paper_market_event`; `process_market_observation` rechecked cash/shares and wrote fill, balance, position, and P&L together. No prior decision-to-order link existed.
- **Rule:** Start records account 1, strategy `sma-crossover`, symbol, interval, order size, and a generation. A unique SQLite claim for account/strategy/symbol/interval/candle precedes image capture. The same frozen PNG and snapshot go through the existing two-call decision route. A veto, bad image, or failed analysis is a skipped event. Buy/sell use configured whole-share size, close uses held shares, and hold/wait create no order. Stop changes the generation and cancels pending automation orders. The next price fill transaction rechecks enabled generation, decision deadline (five minutes after creation), pending status, cash, and shares. Order, fill, and P&L carry the decision ID.
- **Disposable backend command:** `python -m backend.check_paper_automation` on a new `backend/data/automation-test.sqlite3` with `TEST DATA — reviewed paper automation` and a fixed provider response. Expected one fill at $100 for four shares from $1,000, even when the same approved decision is submitted twice; a veto leaves $600/four shares; Stop skips a pending order and a late generation.
- **Backend observed:** The first and repeated submissions returned the same pending order 1. One later test observation filled it; cash `$600`, shares `4`, fill count `1`, P&L row count `1`, and order/fill/P&L decision IDs matched. The veto produced a skipped event and no new order. Stop converted another pending order to skipped. Reopening SQLite preserved cash `$600`, four shares, one fill, and four deduplicated automation events. The server claim returned `claimed=true` once and `false` on a duplicate and after restart.
- **Regression:** `python -m backend.check_paper_account --database backend/data/automation-paper-regression.sqlite3` passed all eleven existing paper checks, including the prior $1,000 → $600/4 → $710/3 → $1,025/0 sequence. `npm run build` succeeded with 17 transformed modules. Python compilation of the changed modules passed.
- **Browser fixture:** Started the fixed provider double on port 8011, FastAPI on 8000 with `MARKET_DATABASE=backend/data/automation-browser-final.sqlite3`, `MARKET_PAPER_FIXTURE=1`, `MARKET_LIVE_FEED=0`, and `MARKET_CANDLE_FILE=backend/data/automation-browser-candles.csv`, and Vue on 5173. This is a separate disposable $1,000 paper account; the provider was **mocked**, not live OpenAI. Initially the CSV had two completed candles. In Vue, entered order size 4 and clicked Start; the two existing candles were baselined without analysis.
- **New completed candle operation:** Added the labeled 14:32 UTC fixture candle (close 13) to the CSV. History polling saw the new completed interval despite the pre-existing WebSocket 403. Vue claimed it, captured a fresh chart PNG, and called analyst and reviewer once each. The visible snapshot `snap_2a875cba01ba463fbb7e25f639a95a26` showed AAPL `1m`, cutoff `2026-11-09T14:32:00Z`, and Python upward crossover. Fixed analyst answers were `buy/upward/sufficient`; fixed reviewer verdict was `accept`; Python rules passed. Decision `dec_f0d80fa50639431a8bbbec7cf9150205` appeared on the pending buy-4 event and order.
- **Browser fill operation:** Clicked **Supply observed price** at `$100` after submission. The visible account became `$600` cash and `4` shares, with fill 1 and zero-fee P&L `$0`. The automation trace showed the same decision ID and filled status. Clicked Stop; Vue showed stopped while retaining the fill trace.
- **Direct SQLite/provider comparison:** The reviewer test double recorded all three actual analyst answers and a PNG SHA-256 matching the stored decision image. SQLite showed the same snapshot/cutoff, analyst choices, reviewer accept, one filled automation event, and matching decision ID on order, fill, and P&L. Cash was `$600`, shares `4`, fill count `1`, and automation `enabled=0`. The mock was used for all automation cases; the earlier authenticated OpenAI check was manual advice only.
- **Manual boundary and limitation:** The manual **Ask about chart** path still calls only snapshot and decision routes and creates no order. In this fixture `MARKET_LIVE_FEED=0`, so `/ws/candles` intentionally closes before accepting and Uvicorn logs 403; the browser automation trigger was verified through history polling and labeled fixture, not a real Yahoo completed candle. No live provider automation execution was attempted.
- **Final check after claim and deadline adjustment:** Recreated the disposable backend fixture and reran `python -m backend.check_paper_automation`; it still returned one fill, `$600` cash, four shares, and a skipped pending order after Stop. `python -m backend.check_pnl_history --database backend/data/automation-pnl-regression.sqlite3` passed all six P&L assertions. Python compilation passed for `backend/main.py`, `backend/paper_trading.py`, `backend/check_paper_automation.py`, and `backend/decision_provider_double.py`; final `npm run build` transformed 17 modules. The decision deadline now compares against current backend time even when a replayed observation carries an old receipt timestamp.
- **Shutdown:** Stopped the test double, FastAPI, and Vite after the final browser check. The separate disposable databases and capture directories remain ignored local evidence; no key was used for the mocked automation run.
- **Stop regression:** After the final rerun, sent another labeled `$101` test observation after Stop. The canceled pending order produced zero additional fills; cash stayed `$600`, shares stayed `4`, and total fill count remained `1`.
- **WebSocket clarification:** Inspected `backend/main.py`: the 403 seen in these offline fixtures is the expected consequence of `MARKET_LIVE_FEED=0` closing `/ws/candles` before `accept()`. It does not prove a live-enabled socket failure. Live-enabled Yahoo completion and automation still require a separate observation.

## 2026-11-12 — Read-only voice for a saved paper decision

- **CHECK:** Read `README.md` and `AGENTS.md`; inspected Git status, decision storage, automation order/fill/P&L schema, Vue chart/decision panel, `frontend/package.json`, its lockfile, `backend/requirements.txt`, and the ignored `.env` assignment name (never the value). Reused Windows 11, Python 3.13.17, FastAPI 0.162.3, Uvicorn 0.54.0, Node 25.7.0, npm 11.10.1, and browser WebRTC. No package installation or manifest/lockfile edit was needed. Followed the [GPT-Live WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc?voice-api=live) and [Live session schema](https://developers.openai.com/api/reference/resources/live/methods/create).
- **Trace:** The selected decision ID joins `decision_records` to its frozen `decision_snapshots`, and looks up any matching `paper_automation_events`, `paper_orders`, `paper_fills`, and `paper_pnl_history`. `backend/voice.py` opens SQLite in read-only mode and sends only that decision's summary as initial GPT-Live context. FastAPI exchanges the browser offer at `/v1/live/sessions` with the backend key. Vue applies the answer, uses microphone and output media tracks, shows transcript deltas and microphone state, and closes tracks/connection on End, disconnect, or failure. The voice route never calls paper execution.
- **Offline provider check (MOCKED):** `python -m backend.check_voice_session --database backend/data/automation-browser-final.sqlite3 --decision-id dec_f0d80fa50639431a8bbbec7cf9150205`. Expected the request body to contain `gpt-live-1`, the selected decision summary, and WebRTC SDP offer; the mocked answer to return its session ID and SDP; a simulated provider disconnect to return a clear failure; decision/order/fill counts to remain unchanged. Observed all assertions passed. Counts before and after were `(1, 1, 1)`. This check made no OpenAI request and played no audio.
- **Direct SQLite comparison (TEST DATA):** Decision `dec_f0d80fa50639431a8bbbec7cf9150205` has analyst `buy/upward/sufficient`, reviewer `accept`, and a `filled` paper event. Order 1 bought four AAPL shares; fill 1 used observation 1 at `$100`; the linked P&L row records `$600` cash and four shares. `GET http://127.0.0.1:5173/api/saved-decisions?symbol=AAPL` returned that decision and those values through Vite's proxy. The browser displayed the same selected decision, proposal, verdict, fill, cash, and shares.
- **Local HTTP failure checks:** `POST http://127.0.0.1:5173/api/voice-sessions` with unknown `dec_missing` and a minimal offer returned `404`. The saved ID with `offer_sdp="bad"` returned `422` and `A valid WebRTC SDP offer is required. Restart voice and try again.` The invalid request did not contact the provider.
- **Browser startup/cleanup:** Opened `http://127.0.0.1:5173/` in the in-app browser and clicked **Start voice**. The page showed `Requesting microphone… · microphone off`; the browser did not resolve the permission request, so no SDP offer or live OpenAI session was created. Clicked **End voice** during startup; the page showed `Ended · microphone off` and re-enabled Start. This is a browser startup cancellation check, not a successful microphone grant or denied-permission check. Access to desktop Chrome through the computer-use tool was denied.
- **Build/startup:** `python -m compileall -q backend/main.py backend/voice.py` passed; `npm run build` transformed 17 modules and passed. Uvicorn started on `127.0.0.1:8000` with the existing disposable fixture, and Vite started on `127.0.0.1:5173` using its tested startup command. The backend key was loaded from the ignored root `.env` into the process without printing it.
- **Live hardware check pending:** The student reported that a microphone is unavailable now. The two requested questions were **not spoken**; no answer was heard or attributed to GPT-Live. Speaker playback, a follow-up in the same session, microphone release after an established session, and denied microphone access remain unverified. Repeat the README voice SmokeTest with a microphone and speaker, compare the spoken answers and captions with this SQLite row, and record the exact actual answers. Any provider access or model limitation should be recorded then.

## 2026-11-12 — One-command offline browser SmokeTest

- **CHECK:** Read `AGENTS.md`, inspected existing backend check scripts, `frontend/package.json` and `package-lock.json`, `backend/requirements.txt`, Git status, Vue automation/replay controls, the provider boundary, and SQLite schema. Local environment: Windows 11, Python 3.13.17, Node 25.7.0, npm 11.10.1, installed Chrome 157.0.8103.52, FastAPI 0.162.3, Uvicorn 0.54.0. No Playwright, Selenium, or Puppeteer package was installed or declared. Node's built-in WebSocket client and Chrome's debugging protocol were available, so no browser download, package installation, dependency manifest edit, or lockfile edit was needed locally. The student approved installing already-pinned backend/frontend packages on ephemeral GitHub runners; the workflow uses `python -m pip install -r backend/requirements.txt` and `npm ci --prefix frontend` there. The workflow has not run yet because these changes have not been committed and pushed.
- **Command:** From the project root, `node scripts/smoke-test.mjs`. Expected: start a fresh SQLite fixture, local model stub, FastAPI and Vite on free localhost ports; wait for readiness; open installed headless Chrome; drive the real Vue UI; compare visible results with direct SQLite; close browser and services even on failure; return nonzero on an unmet assertion. The strengthened final script ran twice successfully. Both runs began with `$1,000` cash and no fill. The first used backend/Vue ports `30037/30038`, the second `59238/59239`; both returned exit code `0`. Their temporary fixture directories were removed. No listener remained on those four ports after exit. Two earlier runs of the same core scenario also passed before the extra sale/duplicate assertions were added.
- **Replay and indicator:** The isolated recorded session had labeled test closes `10, 12, 9` at 14:30, 14:31, and 14:32 UTC, plus a later observation to end the selected minute. In Vue, selected Replay, started it, selected the 14:32 candle, added `Smoke SMA` with window 3, then changed its window to 2. Expected hand result `(12 + 9) / 2 = 10.5`; observed `10.5 price` in the inspector and `settings.window=2` in SQLite on both successful runs. Replay remains read-only for market observations; indicator configuration persists separately.
- **Chart/model boundary (STUBBED):** In live chart mode, added `Fast SMA` with window 1 and clicked **Ask about chart** at 14:32. The local provider stub parsed the request's `input_image`, decompressed its PNG pixel rows, checked readable dimensions and varied pixel bytes, and verified `input_json` symbol `AAPL` and cutoff equal to the final frozen candle time. It returned `wait/downward/sufficient`; the reviewer returned `accept`. The Vue decision panel displayed the known choices and reviewer verdict; direct SQLite showed fill count `0`. A second click received a deliberate provider HTTP `503`; the visible eligibility message included `Analyst call failed`, and fills remained `0`. These are mocked model replies and a mocked failure, not authenticated OpenAI observations.
- **Automation, browser and SQLite:** The stub returned approved `buy/upward` for the newly completed 14:33 test candle, approved `sell/downward` for 14:34, vetoed an upward proposal at 14:35 with `reject_unsupported_signal`, and approved `close/downward` at 14:36. Vue set buy size 4 and later updated sale size to 1. The next eligible fixture prices were supplied through the page at `$100`, `$110`, and `$105` respectively. Expected and observed values in both runs:

  | Event | Cash | Shares | Fills | Realized P&L | Unrealized P&L |
  | --- | ---: | ---: | ---: | ---: | ---: |
  | Fresh account | $1,000 | 0 | 0 | No valuation row | No valuation row |
  | Buy 4 at $100 | $600 | 4 | 1 | $0 at fill | $0 at fill |
  | Sell 1 at $110 | $710 | 3 | 2 | $10 | $30 at the fill price |
  | Reviewer veto | $710 | 3 | 2 | $10 | unchanged |
  | Close 3 at $105 | $1,025 | 0 | 3 | $25 | $0 |

- **Deduplication and Stop:** A duplicate 14:36 CSV event left SQLite orders and fills at 3 and made no new model call. Clicking Stop in Vue, then delivering 14:37, produced a 14:37 candle in backend history but left orders at 3, fills at 3, and the model-stub call count unchanged. SQLite automation events were `filled`, `filled`, `skipped`, `filled` for 14:33 through 14:36. Each run used a new database path; 11 model-stub calls were made per successful run (analyst/reviewer pairs except the deliberate failure). After the partial sale, both the Vue account panel and direct SQLite showed `$10` realized and `$30` unrealized P&L.
- **Failure evidence and AutoLoop cycle 1:** The first attempt returned exit code `1` at the Replay SMA display assertion. Its ignored screenshot and database remain under `backend/data/smoke-runs/smoke-1794520466475-23868/`. The screenshot showed `Smoke SMA` saved with window 2; direct replay inspection showed historical candles but no completion update for earlier minutes. `ReplayEngine` emitted updates only when candle prices changed, so Vue still marked the selected minute as forming and Python returned a warm-up gap. The scoped correction in `backend/replay_session.py` emits an update when a candle's completion status changes. Rerunning the same SmokeTest without weakening the assertion passed; the next clean run also passed. No further AutoLoop cycle was needed.
- **Other failed commands:** An attempted `backend.check_replay_session` invocation against the SmokeTest's 14:29–14:33 database failed because that older check expects its own 15:00 fixture. Two Python compilation commands launched from `frontend/` reported that relative `backend/*.py` paths could not be listed. Re-running compilation from the project root passed. The final Vue `npm run build` transformed 17 modules; `git diff --check` found no whitespace errors (only Windows line-ending notices).
- **CI:** `.github/workflows/smoke-test.yml` runs the same `node scripts/smoke-test.mjs` command on each push using a Windows runner, Python 3.13, Node 24, preinstalled Chrome, and the approved installation of existing lockfile/requirements packages. It uses no provider key. The workflow is configured but its GitHub run is unverified until the reviewed changes are pushed. The live Yahoo receipt/candle, authenticated image-model, and two-way voice microphone/speaker checks remain separate documented observations.
