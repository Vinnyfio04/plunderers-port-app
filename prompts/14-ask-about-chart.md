# Ask about a frozen chart

Read `AGENTS.md`, locate the Vue chart and decision route, and add an
**Ask about chart** workflow. Freeze the selected completed candle, symbol,
interval, chart range, candles, volume, indicator lines, and paper position.
Export the chart-only Lightweight Charts canvas as PNG and send it with the
snapshot to the OpenAI Decisions API as `input_image` plus `input_json` in one
user message.

Ask the named choice questions `action`, `crossover`, and `evidence`. Validate
answers by name, compare the visual crossover with Python, and mark unreadable,
missing, insufficient, or conflicting results ineligible for automation. Save
the capture reference, snapshot, questions, and answers under the decision ID.
This operation is advisory and must not change paper balances or orders.

Verify a recorded crossover in the browser with an HTTP provider test double,
compare the saved PNG hash and SQLite state, and separately attempt one live
OpenAI image request without exposing credentials.
