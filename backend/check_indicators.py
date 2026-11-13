import argparse
import json
from pathlib import Path

from backend.indicators import (
    IndicatorStore,
    calculate_indicator,
    instance_with_values,
    validate_indicator,
)
from backend.timeframe_history import aggregate_timeframe, load_minute_records


FIXTURE = Path(__file__).resolve().parent.parent / "prompts" / "data" / "indicator-fixture.csv"
TEST_LABEL = "TEST DATA — indicator extension verification fixture"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    if database.exists():
        raise FileExistsError(database)
    history = aggregate_timeframe(load_minute_records(FIXTURE), timeframe="1m")

    range_2 = calculate_indicator(
        "price_range", {"window": 2}, history["candles"], history["status"]
    )
    range_3 = calculate_indicator(
        "price_range", {"window": 3}, history["candles"], history["status"]
    )
    sma_2 = calculate_indicator(
        "sma", {"window": 2}, history["candles"], history["status"]
    )
    with IndicatorStore(database) as store:
        stored_range_2 = store.create(
            "AAPL", "1m", "Range 2", "price_range", {"window": 2}
        )
        stored_range_3 = store.create(
            "AAPL", "1m", "Range 3", "price_range", {"window": 3}
        )
        stored_values = [
            instance_with_values(item, history["candles"], history["status"])
            for item in store.list("AAPL", "1m")
        ]

    invalid_error = None
    try:
        validate_indicator("price_range", "Invalid", {"window": 0})
    except ValueError as error:
        invalid_error = str(error)

    with IndicatorStore(database) as reopened:
        reopened_items = reopened.list("AAPL", "1m")

    expected_range_2 = [None, 6.0, 5.0]
    expected_range_3 = [None, None, 6.0]
    observed_range_2 = [item["value"] for item in range_2]
    observed_range_3 = [item["value"] for item in range_3]
    observed_sma_2 = [item["value"] for item in sma_2]
    checks = {
        "range_2_values": observed_range_2 == expected_range_2,
        "range_3_values": observed_range_3 == expected_range_3,
        "sma_uses_shared_interface": observed_sma_2 == [None, 12.5, 13.0],
        "instances_have_independent_settings": (
            stored_range_2.settings == {"window": 2}
            and stored_range_3.settings == {"window": 3}
        ),
        "instances_persist_after_reopen": (
            [item.name for item in reopened_items] == ["Range 2", "Range 3"]
        ),
        "zero_window_is_rejected": (
            invalid_error == "Window must be at least 1 completed candle."
        ),
        "invalid_did_not_remove_valid_instances": len(reopened_items) == 2,
        "output_has_every_candle_time": all(
            len(values) == len(history["candles"])
            for values in (range_2, range_3, sma_2)
        ),
    }
    output = {
        "data_label": TEST_LABEL,
        "fixture": str(FIXTURE),
        "database": str(database),
        "high_low_pairs": [[12, 9], [15, 10], [13, 11]],
        "expected": {
            "Range 2": expected_range_2,
            "Range 3": expected_range_3,
        },
        "observed": {
            "Range 2": observed_range_2,
            "Range 3": observed_range_3,
            "SMA 2": observed_sma_2,
        },
        "stored": stored_values,
        "invalid_error": invalid_error,
        "checks": checks,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
