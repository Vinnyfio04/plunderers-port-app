import argparse
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import json
from typing import Any

import yfinance as yf


def parse_integer(value: Any) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_source_time(value: Any) -> tuple[str | None, str]:
    source_time = parse_integer(value)
    if source_time is None:
        return None, "not supplied"

    if source_time >= 10_000_000_000:
        timestamp_seconds = source_time / 1000
        units = "Unix epoch milliseconds"
    else:
        timestamp_seconds = source_time
        units = "Unix epoch seconds"

    formatted = datetime.fromtimestamp(
        timestamp_seconds,
        tz=timezone.utc,
    ).isoformat().replace("+00:00", "Z")
    return formatted, units


def format_update(
    ticker: str,
    message: dict[str, Any],
    receipt_time: datetime,
    timeout_seconds: float,
) -> dict[str, Any]:
    source_time, source_time_units = format_source_time(message.get("time"))
    day_volume = parse_integer(message.get("day_volume"))
    last_size = parse_integer(message.get("last_size"))

    return {
        "ticker": message.get("id", ticker),
        "price": message.get("price"),
        "source_time_raw": parse_integer(message.get("time")),
        "source_time_utc": source_time,
        "source_time_units": source_time_units,
        "backend_receipt_time_utc": receipt_time.isoformat().replace("+00:00", "Z"),
        "day_volume": day_volume,
        "day_volume_measure": (
            "Cumulative shares traded during the current market day for this equity "
            "as reported by Yahoo Finance; it is not one-minute volume."
        ),
        "last_size": last_size,
        "last_size_measure": (
            "Shares in the most recently reported trade when Yahoo supplies the field."
        ),
        "connection_opened": True,
        "receipt_verified": True,
        "timeout_seconds": timeout_seconds,
        "available_message_fields": sorted(message),
    }


async def receive_one_update(
    ticker: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    queue: asyncio.Queue[tuple[dict[str, Any], datetime]] = asyncio.Queue(maxsize=1)
    websocket = yf.AsyncWebSocket(verbose=False)
    listener: asyncio.Task[None] | None = None
    connection_opened = False

    async def handle_message(message: dict[str, Any]) -> None:
        message_ticker = str(message.get("id", "")).upper()
        if message_ticker and message_ticker != symbol:
            return

        if queue.empty():
            queue.put_nowait((message, datetime.now(timezone.utc)))

    try:
        async with asyncio.timeout(timeout_seconds):
            await websocket.subscribe([symbol])
            connection_opened = True
            listener = asyncio.create_task(websocket.listen(handle_message))
            message, receipt_time = await queue.get()
            return format_update(symbol, message, receipt_time, timeout_seconds)
    except TimeoutError:
        return {
            "ticker": symbol,
            "connection_opened": connection_opened,
            "receipt_verified": False,
            "timeout_seconds": timeout_seconds,
            "observation": "No matching update arrived before the bounded timeout.",
        }
    except Exception as error:
        return {
            "ticker": symbol,
            "connection_opened": connection_opened,
            "receipt_verified": False,
            "timeout_seconds": timeout_seconds,
            "error": f"{type(error).__name__}: {error}",
        }
    finally:
        if listener is not None:
            listener.cancel()
        with suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(websocket.close(), timeout=2)
        if listener is not None:
            with suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(listener, timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Receive at most one Yahoo Finance WebSocket update.",
    )
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--timeout", type=float, default=20.0)
    arguments = parser.parse_args()

    if arguments.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    result = asyncio.run(
        receive_one_update(arguments.ticker, arguments.timeout),
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
