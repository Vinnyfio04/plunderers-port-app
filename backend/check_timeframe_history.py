from datetime import datetime, timedelta, timezone
from pathlib import Path

import exchange_calendars as xcals

from backend.timeframe_history import (
    MinuteRecord,
    aggregate_timeframe,
    load_minute_records,
    parse_utc_timestamp,
)


TEST_DATA_LABEL = "TEST DATA — constructed timeframe aggregation input"
SAMPLE_FILE = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "data"
    / "sample-candles.csv"
)


def utc(value: str) -> datetime:
    return parse_utc_timestamp(value)


def record(
    timestamp: str,
    open_price: int,
    high: int,
    low: int,
    close: int,
    volume: int | None,
    available_at: str | None = None,
) -> MinuteRecord:
    minute = utc(timestamp)
    return MinuteRecord(
        candle={
            "timestamp": timestamp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        available_at=(
            utc(available_at)
            if available_at is not None
            else minute + timedelta(minutes=1)
        ),
    )


def status_for(result: dict, timestamp: str) -> dict:
    return next(item for item in result["status"] if item["timestamp"] == timestamp)


def run_checks() -> dict:
    sample = load_minute_records(SAMPLE_FILE)
    five_minute = aggregate_timeframe(
        sample,
        timeframe="5m",
        as_of=utc("2026-11-09T21:01:00Z"),
    )
    expected_five_minute = {
        "timestamp": "2026-11-09T14:30:00Z",
        "open": 100,
        "high": 105,
        "low": 99,
        "close": 104,
        "volume": 3550,
    }
    five_status = status_for(five_minute, expected_five_minute["timestamp"])

    same_session = [
        *sample,
        record("2026-11-09T14:35:00Z", 104, 106, 103, 105, 400),
    ]
    same_session_five = aggregate_timeframe(
        same_session,
        timeframe="5m",
        as_of=utc("2026-11-09T21:01:00Z"),
    )
    same_session_daily = aggregate_timeframe(
        same_session,
        timeframe="1d",
        as_of=utc("2026-11-09T21:01:00Z"),
    )

    next_session = [
        *same_session,
        record("2026-11-10T14:30:00Z", 106, 108, 105, 107, 500),
    ]
    next_session_daily = aggregate_timeframe(
        next_session,
        timeframe="1d",
        as_of=utc("2026-11-10T21:01:00Z"),
    )

    revision_records = [
        *sample,
        record(
            "2026-11-09T14:31:00Z",
            102,
            110,
            100,
            109,
            900,
            available_at="2026-11-09T15:10:00Z",
        ),
    ]
    before_revision = aggregate_timeframe(
        revision_records,
        timeframe="5m",
        as_of=utc("2026-11-09T15:00:00Z"),
    )
    after_revision = aggregate_timeframe(
        revision_records,
        timeframe="5m",
        as_of=utc("2026-11-09T15:11:00Z"),
    )

    unknown_and_zero = [
        record("2026-11-09T14:30:00Z", 10, 10, 10, 10, 0),
        record("2026-11-09T14:31:00Z", 10, 10, 10, 10, None),
    ]
    unknown_result = aggregate_timeframe(
        unknown_and_zero,
        timeframe="1m",
        as_of=utc("2026-11-09T14:32:00Z"),
    )

    calendar = xcals.get_calendar("XNYS")
    checks = {
        "sample_five_minute_values": five_minute["candles"]
        == [expected_five_minute],
        "sample_five_minute_partial": (
            five_status["available_minutes"] == 3
            and five_status["expected_minutes"] == 5
            and not five_status["coverage_complete"]
        ),
        "sample_daily_partial": (
            len(aggregate_timeframe(sample, "1d")["candles"]) == 1
            and not aggregate_timeframe(sample, "1d")["status"][0][
                "coverage_complete"
            ]
        ),
        "fourth_minute_starts_second_five_minute": [
            candle["timestamp"] for candle in same_session_five["candles"]
        ]
        == ["2026-11-09T14:30:00Z", "2026-11-09T14:35:00Z"],
        "gap_stays_in_same_daily_session": len(same_session_daily["candles"]) == 1,
        "next_session_starts_new_daily_candle": [
            candle["timestamp"] for candle in next_session_daily["candles"]
        ]
        == ["2026-11-09T14:30:00Z", "2026-11-10T14:30:00Z"],
        "revision_replaces_prior_minute": (
            before_revision["candles"][0] == expected_five_minute
            and after_revision["candles"][0]["high"] == 110
            and after_revision["candles"][0]["close"] == 104
            and after_revision["candles"][0]["volume"] == 3600
        ),
        "known_zero_is_distinct_from_unknown": (
            unknown_result["candles"][0]["volume"] == 0
            and unknown_result["status"][0]["volume_known"]
            and unknown_result["candles"][1]["volume"] is None
            and not unknown_result["status"][1]["volume_known"]
        ),
        "calendar_handles_time_change": (
            str(calendar.session_open("2026-07-06"))
            == "2026-07-06 13:30:00+00:00"
            and str(calendar.session_open("2026-11-09"))
            == "2026-11-09 14:30:00+00:00"
        ),
        "calendar_handles_early_close": str(calendar.session_close("2026-11-27"))
        == "2026-11-27 18:00:00+00:00",
    }
    if not all(checks.values()):
        raise AssertionError(f"timeframe aggregation verification failed: {checks}")

    return {
        "data_label": TEST_DATA_LABEL,
        "expected_five_minute": expected_five_minute,
        "observed_five_minute": five_minute["candles"][0],
        "five_minute_status": five_status,
        "second_five_minute": same_session_five["candles"][1],
        "same_session_daily": same_session_daily,
        "next_session_daily_timestamps": [
            candle["timestamp"] for candle in next_session_daily["candles"]
        ],
        "checks": checks,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_checks(), indent=2, sort_keys=True))
