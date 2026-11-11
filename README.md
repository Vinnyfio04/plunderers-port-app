# Live Market Workplace

## Project overview

Live Market Workplace is a lightweight, TradingView-style local application for people who want to observe live markets and make more informed trading decisions. It is aimed especially at less-experienced traders. The planned application will display live data from an external market-data API and provide an agentic helper that explains market context and supports buy/sell decision-making. The helper is advisory; the user remains responsible for every trading decision.

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
- **External services:** A market-data API and an agent/model provider are still to be selected.

## Current status

The first charting vertical slice is complete. FastAPI exposes `GET /api/health` and `GET /api/history`, and the Vue development server forwards `/api` requests to FastAPI. The history endpoint reads synthetic one-minute candles from `prompts/data/sample-candles.csv` using Python's built-in `csv` module. The Vue frontend renders those rows as aligned candlestick and volume series with an interactive UTC candle inspector.

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

The plain `python` command currently resolves to a nonworking Windows Store alias in the checked shell. Until PATH/alias behavior is corrected, use the full Python 3.13 path shown above. Yarn and Bun were not found.

## Dependencies

- FastAPI `0.162.3`
- Uvicorn `0.54.0`
- Vue `3.5.45`
- Vite `8.3.7`
- TradingView Lightweight Charts `5.2.1`
- yfinance `1.8.0`

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

`GET /api/history` returns an array ordered by UTC timestamp with exactly these fields:

```text
timestamp, open, high, low, close, volume
```

Each source row is one minute for one instrument, and its timestamp marks the inclusive start of that minute. The supplied one-minute candles are the base source for future larger-timeframe aggregation, including daily candles.

### Market chart

The frontend uses TradingView Lightweight Charts to display one candlestick and one aligned volume bar per UTC source timestamp. Move the chart crosshair or use the UTC-minute selector to inspect the candle date, time, open, high, low, close, and volume. The current data is labeled as a synthetic one-minute sample.

### Yahoo Finance stream check

The backend includes a bounded yfinance WebSocket check for one ticker. It defaults to `AAPL`, requires no Yahoo login, and exits after its configured receipt timeout plus a short bounded cleanup period.

```powershell
& 'C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe' -m backend.yahoo_stream --ticker AAPL --timeout 20
```

If Yahoo sends an update, the command prints the ticker, price, source timestamp, backend UTC receipt timestamp, and available `day_volume` or `last_size` fields. If no update arrives, it reports whether the socket opened and sets `receipt_verified` to `false`.

The application does not accept or store Yahoo credentials. A personal Yahoo watchlist can be created or managed separately on the Yahoo Finance website, where the user enters credentials directly.

### Start the frontend

Run from the project root in a second PowerShell terminal:

```powershell
Set-Location frontend
npm run dev
```

Open `http://127.0.0.1:5173/`. The frontend proxy health URL is `http://127.0.0.1:5173/api/health`.

### Stop the services

In each service terminal, press `Ctrl+C`. This stop procedure was tested for both Uvicorn and Vite. Stop the frontend and backend separately; neither command edits source files.

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
|-- backend/
|   |-- main.py
|   |-- requirements.txt
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
|   `-- 05-yahoo-finance-stream.md
`-- handoffs/
    |-- create-handoff.md
    `-- current.md
```

See [docs/design-pipeline.md](docs/design-pipeline.md) for planned responsibilities and data flow.
