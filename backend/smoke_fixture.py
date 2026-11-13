"""Seed a disposable, labeled recorded session for the browser SmokeTest."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from backend.market_store import MarketRecorder


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    database = args.database.resolve()
    if database.exists():
        raise FileExistsError(database)
    observations = [
        ("2026-11-09T14:29:59Z", 9, 1000),
        ("2026-11-09T14:30:05Z", 10, 1005),
        ("2026-11-09T14:31:05Z", 12, 1010),
        ("2026-11-09T14:32:05Z", 9, 1015),
        ("2026-11-09T14:33:05Z", 13, 1020),
    ]
    with MarketRecorder(database) as recorder:
        for source_time, price, volume in observations:
            moment = utc(source_time)
            recorder.record_message({
                "id": "AAPL", "time": int(moment.timestamp() * 1000),
                "price": price, "day_volume": volume,
                "test_data": True, "test_data_label": "TEST DATA — offline SmokeTest replay",
            }, moment, ticker="AAPL")
    print(f"Seeded {len(observations)} labeled observations in {database}")


if __name__ == "__main__":
    main()
