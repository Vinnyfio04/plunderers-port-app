# Current project state

**Updated:** November 11, 2026

## Current capability

The Vue development server is connected to FastAPI. `GET /api/history` reads the supplied synthetic one-minute CSV and returns three timestamp-ordered candle objects. The Vue frontend renders those rows with TradingView Lightweight Charts. The backend now also has a bounded yfinance 1.8.0 WebSocket probe for one ticker; the AAPL connection opened, but no live update arrived during the bounded checks.

## Files created or changed

- `backend/main.py`: FastAPI application, health route, CSV loader, and history route.
- `backend/yahoo_stream.py`: bounded single-ticker yfinance WebSocket subscriber and normalized output.
- `backend/requirements.txt`: exact FastAPI, Uvicorn, and yfinance pins.
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

Detailed commands, initial launch failures, corrections, and observed output are in `docs/verification.md`.

## Outstanding questions

- Which market-data API will supply the first feed, and is delayed or simulated data acceptable for development?
- Which instrument should be displayed first?
- Which larger timeframes should be exposed first, and what market-session boundary should define a daily candle?
- Which agent/model provider should power the helper, and what data may be sent to it?
- Should watchlists or preferences persist locally, and is authentication needed initially?
- Should this folder be initialized as a Git repository?
- The plain `python` command remains masked by a Windows Store alias; use the explicit Python path in `README.md`.
- A real Yahoo payload is still needed to verify price, source-time units, and live volume values.

## Next task

Repeat the bounded AAPL probe during active updates to capture one payload, then decide whether to expose the latest received quote through FastAPI and the Vue chart.
