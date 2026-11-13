# Paper account profit-and-loss history

Read AGENTS.md and inspect the SQLite paper account. Add a profit-and-loss
(P&L) history that a student can read as a table in Vue. Record a row after
each fill and when a completed candle supplies a new valuation price for an
open position. Link each row to the paper account, symbol, event, timestamp,
and price used. Reprocessing the same event must preserve a single entry.

Use weighted average purchase cost per share for this long-only account. A
sale realizes the number of shares sold times the difference between its fill
price and the average cost. A partial sale keeps the remaining shares at that
average cost. Unrealized P&L is the open quantity times the change from average
cost to the valuation price. Record cumulative realized P&L, unrealized P&L
and their sum. Show the time and source of the valuation price. If an open
position has no usable price, label its valuation as unavailable. Keep earlier
rows available when a new price arrives or the position closes.

Run the zero-fee $1,000 fixture specified in the task, compare the Vue table
with direct SQLite before and after a backend restart, and record the result in
`docs/verification.md`.
