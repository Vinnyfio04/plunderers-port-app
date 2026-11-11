# Design pipeline

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

The user remains the decision-maker. The initial design does not include automatic order execution.

## File and directory responsibilities

- `backend/`: Python domain logic, market-data clients, validation, agent coordination, and FastAPI routes.
- `frontend/`: Vue components, client-side state, user input, charts, and visible error/loading states.
- `docs/`: Design decisions, data-flow notes, verification commands, and observed results.
- `prompts/`: Numbered major prompts that led to project changes.
- `handoffs/`: Instructions and current state for safely ending and resuming work.
- `README.md`: Purpose, prerequisites, setup, and only those run commands that have been tested.
- `AGENTS.md`: Standing workflow, safety, dependency, testing, and review rules.

## What exists today

As of November 10, 2026, the first frontend-to-backend path exists:

- `backend/main.py` exposes `GET /api/health` through FastAPI.
- `backend/main.py` reads the supplied one-minute CSV with Python's built-in `csv` module and exposes its ordered rows through `GET /api/history`.
- `backend/yahoo_stream.py` uses yfinance's asynchronous WebSocket client for a bounded, single-ticker live-stream probe and reports connection and receipt status without credentials.
- `prompts/data/sample-candles.csv` is the base-resolution candle source; future larger timeframes, including daily candles, should aggregate from these one-minute rows.
- Uvicorn serves the backend on `127.0.0.1:8000`.
- Vite serves the Vue frontend on `127.0.0.1:5173`.
- `frontend/vite.config.js` forwards `/api` requests to FastAPI.
- `frontend/src/chartAdapter.js` converts every ISO UTC timestamp to Unix seconds for both the candlestick and volume series, keeping them aligned to the same one-minute slot.
- The Vue page requests `/api/history`, displays separate candles and volume bars, and exposes crosshair-driven plus selector-driven candle details.
- The chart and page include the required TradingView attribution logo, notice, and link.
- Backend and frontend dependency declarations and the frontend lockfile exist.

The Yahoo connection probe exists, but no live update has yet been received and no live data is routed into FastAPI or the chart. Timeframe aggregation, a model provider, database, authentication, watchlist, and trading-helper workflow do not exist yet.

## Next design decisions

1. Select a market-data API and clarify whether its feed is real-time, delayed, or simulated.
2. Select the agent/model provider and define what data may be sent to it.
3. Decide the initial instrument types and smallest user workflow.
4. Decide whether watchlists or preferences must persist locally.
5. Agree on package versions and obtain approval before adding manifests or installing project dependencies.
