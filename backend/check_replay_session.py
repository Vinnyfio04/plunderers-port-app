import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from backend.market_store import MarketRecorder
from backend.replay_session import ReplayEngine, RecordedSessionReader


TEST_DATA_LABEL = "TEST DATA — recorded session replay verification input"


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def message(source_time: str, price: float, volume: int) -> dict:
    parsed = utc(source_time)
    return {
        "id": "AAPL",
        "time": int(parsed.timestamp() * 1000),
        "price": price,
        "day_volume": volume,
        "test_data": True,
        "test_data_label": TEST_DATA_LABEL,
    }


def create_test_session(database_path: Path) -> None:
    if database_path.exists():
        raise FileExistsError(database_path)
    with MarketRecorder(database_path) as recorder:
        recorder.record_message(
            message("2026-11-09T14:59:59Z", 99, 1000),
            utc("2026-11-09T14:59:59.100Z"),
        )
        recorder.record_message(
            message("2026-11-09T15:00:05Z", 100, 1004),
            utc("2026-11-09T15:00:05.100Z"),
        )
        original_close = recorder.record_message(
            message("2026-11-09T15:00:50Z", 101, 1011),
            utc("2026-11-09T15:00:50.100Z"),
        )
        recorder.record_message(
            message("2026-11-09T15:00:20Z", 103, 1009),
            utc("2026-11-09T15:01:05Z"),
        )
        recorder.record_message(
            message("2026-11-09T15:00:50Z", 102, 1012),
            utc("2026-11-09T15:01:10Z"),
            supersedes_observation_id=original_close.observation_id,
        )


def run_checks(database_path: Path) -> dict:
    reader = RecordedSessionReader(database_path)
    engine = ReplayEngine(database_path)
    start = utc("2026-11-09T14:59:00Z")
    end = utc("2026-11-09T15:01:00Z")
    count_before = reader.observation_count()
    first = engine.replay("AAPL", "1m", start, end)
    count_after_first = reader.observation_count()
    second = engine.replay("AAPL", "1m", start, end)
    count_after_second = reader.observation_count()
    empty = engine.replay(
        "AAPL",
        "1m",
        utc("2026-11-10T14:30:00Z"),
        utc("2026-11-10T15:00:00Z"),
    )

    final_candle = next(
        candle
        for candle in first["final_candles"]
        if candle["timestamp"] == "2026-11-09T15:00:00Z"
    )
    late_event = first["events"][3]
    revision_event = first["events"][4]
    expected_candle = {
        "timestamp": "2026-11-09T15:00:00Z",
        "open": 100.0,
        "high": 103.0,
        "low": 100.0,
        "close": 102.0,
        "volume": 12,
    }
    checks = {
        "selection_is_available": reader.selections()[0]["ticker"] == "AAPL",
        "receipt_order_is_preserved": [
            event["receipt_id"] for event in first["events"]
        ]
        == [1, 2, 3, 4, 5],
        "source_times_are_preserved": (
            late_event["replay_observation_time"] == "2026-11-09T15:00:20Z"
            and late_event["replay_receipt_time"] == "2026-11-09T15:01:05Z"
        ),
        "late_arrival_updates_original_minute": any(
            update["candle"]["high"] == 103.0
            for update in late_event["updates"]
            if update["candle"]["timestamp"] == "2026-11-09T15:00:00Z"
        ),
        "revision_updates_close_and_volume": (
            revision_event["relationship"] == "revision"
            and any(
                update["candle"] == expected_candle
                for update in revision_event["updates"]
            )
        ),
        "final_values_match_expected": final_candle == expected_candle,
        "source_database_is_unchanged": (
            count_before == 5
            and count_after_first == count_before
            and count_after_second == count_before
            and first["stored_observation_count_before"]
            == first["stored_observation_count_after"]
        ),
        "second_run_is_identical": first == second,
        "empty_selection_is_reported": empty["events"] == [],
    }
    if not all(checks.values()):
        raise AssertionError(f"recorded session replay verification failed: {checks}")

    return {
        "data_label": TEST_DATA_LABEL,
        "database": str(database_path),
        "selection": reader.selections()[0],
        "expected_candle": expected_candle,
        "observed_candle": final_candle,
        "late_event": {
            "source_time": late_event["replay_observation_time"],
            "receipt_time": late_event["replay_receipt_time"],
            "sequence": late_event["sequence"],
        },
        "revision_event": {
            "source_time": revision_event["replay_observation_time"],
            "receipt_time": revision_event["replay_receipt_time"],
            "sequence": revision_event["sequence"],
        },
        "stored_observation_count": count_before,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify read-only recorded session replay.",
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--create-test-session", action="store_true")
    arguments = parser.parse_args()
    database_path = arguments.database.expanduser().resolve()
    if arguments.create_test_session:
        create_test_session(database_path)
    print(json.dumps(run_checks(database_path), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
