import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from backend.market_store import DEFAULT_DATABASE, MarketRecorder


ONE_MINUTE_MS = 60_000


@dataclass(frozen=True)
class CandleAggregation:
    candles: list[dict[str, Any]]
    minute_status: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_timestamp(epoch_ms: int) -> str:
    return (
        datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def normalize_as_of(as_of: datetime) -> datetime:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(timezone.utc)


def minute_volume(
    observations: list[dict[str, Any]],
    minute_start_ms: int,
) -> int | None:
    baseline = next(
        (
            observation["day_volume"]
            for observation in reversed(observations)
            if observation["source_time_epoch_ms"] < minute_start_ms
            and observation["day_volume"] is not None
        ),
        None,
    )
    if baseline is None:
        return None

    minute_end_ms = minute_start_ms + ONE_MINUTE_MS
    cumulative_values = [
        observation["day_volume"]
        for observation in observations
        if minute_start_ms
        <= observation["source_time_epoch_ms"]
        < minute_end_ms
        and observation["day_volume"] is not None
    ]
    if not cumulative_values:
        return None

    source_ordered_totals = [baseline, *cumulative_values]
    if any(
        current < previous
        for previous, current in zip(
            source_ordered_totals,
            source_ordered_totals[1:],
        )
    ):
        return None

    return cumulative_values[-1] - baseline


def aggregate_ticker(
    recorder: MarketRecorder,
    ticker: str,
    as_of: datetime,
) -> CandleAggregation:
    evaluation_time = normalize_as_of(as_of)
    observations = recorder.list_effective_observations(ticker)
    minute_starts = sorted(
        {
            observation["source_time_epoch_ms"] // ONE_MINUTE_MS * ONE_MINUTE_MS
            for observation in observations
        }
    )

    candles: list[dict[str, Any]] = []
    minute_status: list[dict[str, Any]] = []
    for minute_start_ms in minute_starts:
        minute_end_ms = minute_start_ms + ONE_MINUTE_MS
        minute_observations = [
            observation
            for observation in observations
            if minute_start_ms
            <= observation["source_time_epoch_ms"]
            < minute_end_ms
        ]
        prices = [observation["price"] for observation in minute_observations]
        timestamp = utc_timestamp(minute_start_ms)
        candles.append(
            {
                "timestamp": timestamp,
                "open": prices[0],
                "high": max(prices),
                "low": min(prices),
                "close": prices[-1],
                "volume": minute_volume(observations, minute_start_ms),
            }
        )
        minute_end = datetime.fromtimestamp(
            minute_end_ms / 1000,
            tz=timezone.utc,
        )
        minute_status.append(
            {
                "timestamp": timestamp,
                "ended": evaluation_time >= minute_end,
            }
        )

    return CandleAggregation(candles=candles, minute_status=minute_status)


def parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return normalize_as_of(parsed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate stored market observations into one-minute candles.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--as-of",
        type=parse_utc_datetime,
        default=datetime.now(timezone.utc),
        help="UTC evaluation time, for example 2026-11-09T15:01:00Z.",
    )
    arguments = parser.parse_args()

    with MarketRecorder(arguments.database) as recorder:
        result = aggregate_ticker(recorder, arguments.ticker, arguments.as_of)

    print(
        json.dumps(
            {
                "ticker": arguments.ticker.strip().upper(),
                **result.to_dict(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
