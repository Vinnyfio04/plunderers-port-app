import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from backend.market_store import MarketRecorder


TEST_DATA_LABEL = "TEST DATA — constructed recorder verification input"


def utc_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify market-message deduplication in a disposable database.",
    )
    parser.add_argument("--database", type=Path, required=True)
    arguments = parser.parse_args()
    database_path = arguments.database.expanduser().resolve()

    if database_path.exists():
        parser.error("verification database must not already exist")

    original = {
        "id": "AAPL",
        "price": 101.0,
        "time": 1794407400000,
        "day_volume": 1250000,
        "last_size": 100,
        "test_data": True,
        "test_data_label": TEST_DATA_LABEL,
    }
    changed_same_source_time = {
        **original,
        "price": 101.25,
        "day_volume": 1250850,
    }

    with MarketRecorder(database_path) as recorder:
        first = recorder.record_message(
            original,
            utc_time("2026-11-11T14:30:01Z"),
        )
        exact_repeat = recorder.record_message(
            dict(original),
            utc_time("2026-11-11T14:30:02Z"),
        )
        changed = recorder.record_message(
            changed_same_source_time,
            utc_time("2026-11-11T14:30:03Z"),
        )
        before_restart = {
            "observations": recorder.list_observations(),
            "receipts": recorder.list_receipts(),
        }

    # Opening a new recorder instance simulates a restarted backend process.
    with MarketRecorder(database_path) as restarted_recorder:
        after_restart = {
            "observations": restarted_recorder.list_observations(),
            "receipts": restarted_recorder.list_receipts(),
        }

    checks = {
        "two_unique_observations": len(after_restart["observations"]) == 2,
        "three_receipts": len(after_restart["receipts"]) == 3,
        "repeat_reuses_observation": (
            first.observation_id == exact_repeat.observation_id
            and exact_repeat.is_exact_repeat
        ),
        "changed_payload_is_retained_separately": (
            changed.observation_id != first.observation_id
            and changed.action == "distinct_same_source_time"
            and changed.supersedes_observation_id is None
        ),
        "records_survive_restart": before_restart == after_restart,
        "receipt_order_preserved": [
            receipt["receipt_id"] for receipt in after_restart["receipts"]
        ] == [1, 2, 3],
    }

    if not all(checks.values()):
        raise AssertionError(f"recorder verification failed: {checks}")

    output = {
        "data_label": TEST_DATA_LABEL,
        "database": str(database_path),
        "record_results": {
            "first": first.to_dict(),
            "exact_repeat": exact_repeat.to_dict(),
            "changed_same_source_time": changed.to_dict(),
        },
        "stored_after_backend_restart": after_restart,
        "checks": checks,
        "reader_guidance": (
            "Count rows from observations to avoid counting exact repeats twice. "
            "Use receipts for the complete arrival audit trail. Distinct payloads "
            "with the same source time remain separate unless a trusted correction "
            "explicitly supplies supersedes_observation_id."
        ),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
