import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import exchange_calendars as xcals
import pandas as pd


Timeframe = Literal["1m", "5m", "15m", "1h", "1d"]
SUPPORTED_TIMEFRAMES: tuple[Timeframe, ...] = ("1m", "5m", "15m", "1h", "1d")
TIMEFRAME_MINUTES: dict[Timeframe, int | None] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "1d": None,
}
CANDLE_FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]
DEFAULT_CALENDAR = "XNYS"


@dataclass(frozen=True)
class MinuteRecord:
    candle: dict[str, Any]
    available_at: datetime


def parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("candle timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def format_utc_timestamp(value: datetime | pd.Timestamp) -> str:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


def parse_price(value: str) -> int | float:
    price = float(value)
    return int(price) if price.is_integer() else price


def load_minute_records(path: Path) -> list[MinuteRecord]:
    with path.open(encoding="utf-8", newline="") as candle_file:
        reader = csv.DictReader(candle_file)
        if reader.fieldnames != CANDLE_FIELDS:
            raise ValueError(
                f"Expected CSV fields {CANDLE_FIELDS}, got {reader.fieldnames}"
            )

        records = []
        for row in reader:
            timestamp = parse_utc_timestamp(row["timestamp"])
            records.append(
                MinuteRecord(
                    candle={
                        "timestamp": format_utc_timestamp(timestamp),
                        "open": parse_price(row["open"]),
                        "high": parse_price(row["high"]),
                        "low": parse_price(row["low"]),
                        "close": parse_price(row["close"]),
                        "volume": int(row["volume"]),
                    },
                    available_at=timestamp + timedelta(minutes=1),
                )
            )
    return records


def _latest_available_minutes(
    records: list[MinuteRecord],
    as_of: datetime | None,
) -> list[MinuteRecord]:
    cutoff = as_of.astimezone(timezone.utc) if as_of is not None else None
    latest: dict[str, tuple[datetime, int, MinuteRecord]] = {}
    for sequence, record in enumerate(records):
        available_at = record.available_at.astimezone(timezone.utc)
        if cutoff is not None and available_at > cutoff:
            continue
        timestamp = record.candle["timestamp"]
        candidate = (available_at, sequence, record)
        if timestamp not in latest or candidate[:2] > latest[timestamp][:2]:
            latest[timestamp] = candidate
    return [entry[2] for entry in latest.values()]


def _session_details(calendar, minute: datetime):
    minute_timestamp = pd.Timestamp(minute)
    try:
        session = calendar.minute_to_session(minute_timestamp, direction="none")
    except ValueError:
        return None
    return (
        session,
        calendar.session_open(session),
        calendar.session_close(session),
    )


def aggregate_timeframe(
    records: list[MinuteRecord],
    timeframe: Timeframe = "1m",
    as_of: datetime | None = None,
    calendar_name: str = DEFAULT_CALENDAR,
) -> dict[str, Any]:
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    if as_of is not None and as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    calendar = xcals.get_calendar(calendar_name)
    effective_records = _latest_available_minutes(records, as_of)
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    interval_minutes = TIMEFRAME_MINUTES[timeframe]

    for record in effective_records:
        minute = parse_utc_timestamp(record.candle["timestamp"])
        details = _session_details(calendar, minute)
        if details is None:
            continue
        session, session_open, session_close = details

        if interval_minutes is None:
            interval_start = session_open
            interval_end = session_close
        else:
            elapsed_minutes = int(
                (pd.Timestamp(minute) - session_open).total_seconds() // 60
            )
            interval_start = session_open + pd.Timedelta(
                minutes=(elapsed_minutes // interval_minutes) * interval_minutes
            )
            interval_end = min(
                interval_start + pd.Timedelta(minutes=interval_minutes),
                session_close,
            )

        timestamp = format_utc_timestamp(interval_start)
        key = (str(session), timestamp)
        group = grouped.setdefault(
            key,
            {
                "timestamp": timestamp,
                "interval_end": interval_end,
                "session": str(session.date()),
                "session_open": session_open,
                "session_close": session_close,
                "expected_minutes": int(
                    (interval_end - interval_start).total_seconds() // 60
                ),
                "records": [],
            },
        )
        group["records"].append(record)

    evaluation_time = (
        as_of.astimezone(timezone.utc)
        if as_of is not None
        else datetime.now(timezone.utc)
    )
    candles: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    for group in sorted(grouped.values(), key=lambda item: item["timestamp"]):
        minute_records = sorted(
            group["records"],
            key=lambda record: record.candle["timestamp"],
        )
        source = [record.candle for record in minute_records]
        volume_known = all(candle["volume"] is not None for candle in source)
        candle = {
            "timestamp": group["timestamp"],
            "open": source[0]["open"],
            "high": max(item["high"] for item in source),
            "low": min(item["low"] for item in source),
            "close": source[-1]["close"],
            "volume": (
                sum(item["volume"] for item in source) if volume_known else None
            ),
        }
        candles.append(candle)
        available_minutes = len(source)
        status.append(
            {
                "timestamp": group["timestamp"],
                "session": group["session"],
                "session_open": format_utc_timestamp(group["session_open"]),
                "session_close": format_utc_timestamp(group["session_close"]),
                "available_minutes": available_minutes,
                "expected_minutes": group["expected_minutes"],
                "coverage_complete": available_minutes == group["expected_minutes"],
                "interval_ended": evaluation_time
                >= group["interval_end"].to_pydatetime(),
                "volume_known": volume_known,
            }
        )

    return {
        "timeframe": timeframe,
        "calendar": calendar_name,
        "as_of": format_utc_timestamp(evaluation_time),
        "candles": candles,
        "status": status,
    }
