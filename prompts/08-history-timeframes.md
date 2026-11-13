# Add exchange-session history timeframes

Read `AGENTS.md` and find the backend's one-minute candles. Let `GET
/api/history` return `1m`, `5m`, `15m`, `1h`, or `1d` candles for one symbol,
defaulting to one minute. Derive larger intervals from the same one-minute
data on request and retain the six candle fields.

Use the stock exchange's regular session, align intraday groups to its open,
and make a daily candle cover one session with the session-open UTC timestamp.
Follow early closes and time changes, and keep session minutes together across
gaps. Aggregate OHLC and summed volume. Revisions replace earlier minute
values. Report unknown volume, coverage, and completion outside the candle.
During live use or replay, include only minutes available at the displayed
time.

Verify the supplied 14:30–14:32 sample as a partial five-minute candle with
OHLC `100/105/99/104` and volume `3550`. Add constructed test minutes at 14:35
and in the next session to verify five-minute and daily boundaries. Record all
comparisons in `docs/verification.md`.
