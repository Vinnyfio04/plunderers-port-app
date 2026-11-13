# Aggregate stored observations into one-minute candles

Read `AGENTS.md` and inspect the observations stored by the backend. Write the
Python logic that groups one ticker's observations into one-minute candles,
the same base resolution as the CSV. For each minute, return exactly
`timestamp`, `open`, `high`, `low`, `close`, and `volume`. Use the minute's
start date and time in UTC for `timestamp`. Track whether the minute has ended
separately. Use source time to order prices within the minute.

Document how late observations and identifiable corrections update a candle.

Verify a one-minute candle with these constructed test observations, all on
November 9, 2026 UTC. The volume value is the running session total.

| Source time | Price | Cumulative volume |
|---|---:|---:|
| 14:59:59 | 99 | 1000 |
| 15:00:05 | 100 | 1004 |
| 15:00:20 | 103 | 1009 |
| 15:00:50 | 101 | 1011 |

The `2026-11-09T15:00:00Z` candle must be open 100, high 103, low 100,
close 101, and volume 11. Check it before and after the minute ends, deliver
the middle observation late, and check the final values again. Report volume
as unknown when the cumulative baseline is unavailable or the session total
resets. Record the rules and expected and observed results in project docs.
