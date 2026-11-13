import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from backend.candle_aggregation import aggregate_ticker
from backend.market_store import MarketRecorder


TEST_DATA_LABEL = "TEST DATA — constructed one-minute candle verification input"
EXPECTED_CANDLE = {
    "timestamp": "2026-11-09T15:00:00Z",
    "open": 100.0,
    "high": 103.0,
    "low": 100.0,
    "close": 101.0,
    "volume": 11,
}


def utc_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def epoch_ms(value: str) -> int:
    return int(utc_time(value).timestamp() * 1000)


def message(ticker: str, source_time: str, price: float, volume: int) -> dict:
    return {
        "id": ticker,
        "time": epoch_ms(source_time),
        "price": price,
        "day_volume": volume,
        "test_data": True,
        "test_data_label": TEST_DATA_LABEL,
    }


def candle_at(result, timestamp: str) -> dict:
    return next(candle for candle in result.candles if candle["timestamp"] == timestamp)


def status_at(result, timestamp: str) -> bool:
    return next(
        status["ended"]
        for status in result.minute_status
        if status["timestamp"] == timestamp
    )


def record_standard_sequence(recorder: MarketRecorder, ticker: str) -> None:
    observations = [
        ("2026-11-09T14:59:59Z", 99, 1000, "2026-11-09T14:59:59.100Z"),
        ("2026-11-09T15:00:05Z", 100, 1004, "2026-11-09T15:00:05.100Z"),
        ("2026-11-09T15:00:20Z", 103, 1009, "2026-11-09T15:00:20.100Z"),
        ("2026-11-09T15:00:50Z", 101, 1011, "2026-11-09T15:00:50.100Z"),
    ]
    for source_time, price, volume, receipt_time in observations:
        recorder.record_message(
            message(ticker, source_time, price, volume),
            utc_time(receipt_time),
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify one-minute candle aggregation in a disposable database.",
    )
    parser.add_argument("--database", type=Path, required=True)
    arguments = parser.parse_args()
    database_path = arguments.database.expanduser().resolve()
    if database_path.exists():
        parser.error("verification database must not already exist")

    target_timestamp = EXPECTED_CANDLE["timestamp"]
    with MarketRecorder(database_path) as recorder:
        record_standard_sequence(recorder, "TEST-NORMAL")
        before_end_result = aggregate_ticker(
            recorder,
            "TEST-NORMAL",
            utc_time("2026-11-09T15:00:55Z"),
        )
        after_end_result = aggregate_ticker(
            recorder,
            "TEST-NORMAL",
            utc_time("2026-11-09T15:01:00Z"),
        )

        recorder.record_message(
            message("TEST-LATE", "2026-11-09T14:59:59Z", 99, 1000),
            utc_time("2026-11-09T14:59:59.100Z"),
        )
        recorder.record_message(
            message("TEST-LATE", "2026-11-09T15:00:05Z", 100, 1004),
            utc_time("2026-11-09T15:00:05.100Z"),
        )
        recorder.record_message(
            message("TEST-LATE", "2026-11-09T15:00:50Z", 101, 1011),
            utc_time("2026-11-09T15:00:50.100Z"),
        )
        before_late_result = aggregate_ticker(
            recorder,
            "TEST-LATE",
            utc_time("2026-11-09T15:01:01Z"),
        )
        recorder.record_message(
            message("TEST-LATE", "2026-11-09T15:00:20Z", 103, 1009),
            utc_time("2026-11-09T15:01:05Z"),
        )
        after_late_result = aggregate_ticker(
            recorder,
            "TEST-LATE",
            utc_time("2026-11-09T15:01:06Z"),
        )

        recorder.record_message(
            message("TEST-NO-BASELINE", "2026-11-09T15:00:05Z", 100, 1004),
            utc_time("2026-11-09T15:00:05.100Z"),
        )
        no_baseline_result = aggregate_ticker(
            recorder,
            "TEST-NO-BASELINE",
            utc_time("2026-11-09T15:00:55Z"),
        )

        recorder.record_message(
            message("TEST-RESET", "2026-11-09T14:59:59Z", 99, 1000),
            utc_time("2026-11-09T14:59:59.100Z"),
        )
        recorder.record_message(
            message("TEST-RESET", "2026-11-09T15:00:05Z", 100, 4),
            utc_time("2026-11-09T15:00:05.100Z"),
        )
        reset_result = aggregate_ticker(
            recorder,
            "TEST-RESET",
            utc_time("2026-11-09T15:00:55Z"),
        )

        recorder.record_message(
            message("TEST-CORRECTION", "2026-11-09T14:59:59Z", 99, 1000),
            utc_time("2026-11-09T14:59:59.100Z"),
        )
        recorder.record_message(
            message("TEST-CORRECTION", "2026-11-09T15:00:05Z", 100, 1004),
            utc_time("2026-11-09T15:00:05.100Z"),
        )
        original_middle = recorder.record_message(
            message("TEST-CORRECTION", "2026-11-09T15:00:20Z", 103, 1009),
            utc_time("2026-11-09T15:00:20.100Z"),
        )
        recorder.record_message(
            message("TEST-CORRECTION", "2026-11-09T15:00:50Z", 101, 1011),
            utc_time("2026-11-09T15:00:50.100Z"),
        )
        recorder.record_message(
            message("TEST-CORRECTION", "2026-11-09T15:00:20Z", 104, 1009),
            utc_time("2026-11-09T15:01:10Z"),
            supersedes_observation_id=original_middle.observation_id,
        )
        correction_result = aggregate_ticker(
            recorder,
            "TEST-CORRECTION",
            utc_time("2026-11-09T15:01:11Z"),
        )

    before_end = candle_at(before_end_result, target_timestamp)
    after_end = candle_at(after_end_result, target_timestamp)
    before_late = candle_at(before_late_result, target_timestamp)
    after_late = candle_at(after_late_result, target_timestamp)
    no_baseline = candle_at(no_baseline_result, target_timestamp)
    reset = candle_at(reset_result, target_timestamp)
    corrected = candle_at(correction_result, target_timestamp)
    checks = {
        "expected_before_minute_end": before_end == EXPECTED_CANDLE,
        "minute_open_before_end": not status_at(before_end_result, target_timestamp),
        "expected_after_minute_end": after_end == EXPECTED_CANDLE,
        "minute_ended_after_boundary": status_at(after_end_result, target_timestamp),
        "late_middle_observation_recomputes_high": (
            before_late["high"] == 101.0 and after_late == EXPECTED_CANDLE
        ),
        "late_arrival_does_not_change_close": after_late["close"] == 101.0,
        "missing_baseline_volume_is_unknown": no_baseline["volume"] is None,
        "reset_volume_is_unknown": reset["volume"] is None,
        "identified_correction_replaces_superseded_value": (
            corrected
            == {
                **EXPECTED_CANDLE,
                "high": 104.0,
            }
        ),
    }
    if not all(checks.values()):
        raise AssertionError(f"candle aggregation verification failed: {checks}")

    print(
        json.dumps(
            {
                "data_label": TEST_DATA_LABEL,
                "database": str(database_path),
                "expected_candle": EXPECTED_CANDLE,
                "before_minute_end": {
                    "candle": before_end,
                    "ended": status_at(before_end_result, target_timestamp),
                },
                "after_minute_end": {
                    "candle": after_end,
                    "ended": status_at(after_end_result, target_timestamp),
                },
                "late_delivery": {
                    "before_late_observation": before_late,
                    "after_late_observation": after_late,
                },
                "unknown_volume": {
                    "missing_baseline": no_baseline["volume"],
                    "session_total_reset": reset["volume"],
                },
                "identified_correction": corrected,
                "checks": checks,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
