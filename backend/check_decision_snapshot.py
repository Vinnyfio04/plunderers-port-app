import argparse
import json
from pathlib import Path

from backend.decisions import DecisionStore
from backend.indicators import IndicatorStore
from backend.market_store import MarketRecorder
from backend.paper_trading import PaperAccount
from backend.timeframe_history import aggregate_timeframe, load_minute_records


FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "data"
    / "indicator-fixture.csv"
)
TEST_LABEL = "TEST DATA — recorded downward crossover decision fixture"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--captures", type=Path, required=True)
    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    captures = args.captures.expanduser().resolve()
    if database.exists():
        raise FileExistsError(database)

    history = aggregate_timeframe(load_minute_records(FIXTURE), timeframe="1m")
    with MarketRecorder(database):
        pass
    with PaperAccount(database, 1000) as paper, IndicatorStore(database) as indicators:
        indicators.create("AAPL", "1m", "Fast SMA", "sma", {"window": 1})
        indicators.create("AAPL", "1m", "Slow SMA", "sma", {"window": 2})
        decisions = DecisionStore(database, indicators, paper, captures)
        snapshot = decisions.create_snapshot(
            "AAPL",
            "1m",
            history["candles"][-1]["timestamp"],
            history["candles"],
        )
        decisions.close()

    checks = {
        "fixture_has_three_candles": len(snapshot["candles"]) == 3,
        "cutoff_is_completed_third_candle": (
            snapshot["cutoff"] == "2026-11-09T14:32:00Z"
        ),
        "python_records_downward_crossover": (
            snapshot["python_crossover"]["signal"] == "downward"
        ),
        "fast_and_slow_values_are_traceable": (
            snapshot["python_crossover"]["previous"]["fast"] == 14
            and snapshot["python_crossover"]["previous"]["slow"] == 12.5
            and snapshot["python_crossover"]["current"]["fast"] == 12
            and snapshot["python_crossover"]["current"]["slow"] == 13
        ),
        "paper_account_is_flat": snapshot["paper_position"]["shares"] == 0,
        "paper_order_count_is_zero": snapshot["paper_position"]["order_count"] == 0,
    }
    print(json.dumps({
        "data_label": TEST_LABEL,
        "database": str(database),
        "fixture": str(FIXTURE),
        "snapshot": snapshot,
        "checks": checks,
    }, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
