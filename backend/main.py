import csv
from pathlib import Path

from fastapi import FastAPI


app = FastAPI(title="Live Market Workplace API")

CANDLE_FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]
CANDLE_FILE = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "data"
    / "sample-candles.csv"
)


def parse_price(value: str) -> int | float:
    price = float(value)
    return int(price) if price.is_integer() else price


def load_candles() -> list[dict[str, str | int | float]]:
    with CANDLE_FILE.open(encoding="utf-8", newline="") as candle_file:
        reader = csv.DictReader(candle_file)

        if reader.fieldnames != CANDLE_FIELDS:
            raise ValueError(
                f"Expected CSV fields {CANDLE_FIELDS}, got {reader.fieldnames}"
            )

        candles = [
            {
                "timestamp": row["timestamp"],
                "open": parse_price(row["open"]),
                "high": parse_price(row["high"]),
                "low": parse_price(row["low"]),
                "close": parse_price(row["close"]),
                "volume": int(row["volume"]),
            }
            for row in reader
        ]

    return sorted(candles, key=lambda candle: candle["timestamp"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "backend"}


@app.get("/api/history")
def history() -> list[dict[str, str | int | float]]:
    return load_candles()
