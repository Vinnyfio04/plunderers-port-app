import argparse
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import yfinance as yf

from backend.market_store import DEFAULT_DATABASE, MarketRecorder, describe_source_time


MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
ConnectedHandler = Callable[[], Awaitable[None]]


async def listen_for_updates(
    ticker: str,
    on_message: MessageHandler,
    on_connected: ConnectedHandler | None = None,
) -> None:
    """Run the project's shared Yahoo subscription until cancelled or disconnected."""
    symbol = ticker.strip().upper()
    websocket = yf.AsyncWebSocket(verbose=False)
    try:
        await websocket.subscribe([symbol])
        if on_connected is not None:
            await on_connected()
        await websocket.listen(on_message)
    finally:
        with suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(websocket.close(), timeout=2)


def parse_integer(value: Any) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_source_time(value: Any) -> tuple[str | None, str]:
    source_time = describe_source_time(value)
    return source_time["source_time_utc"], source_time["source_time_units"]


def format_update(
    ticker: str,
    message: dict[str, Any],
    receipt_time: datetime,
    timeout_seconds: float,
    database_path: Path,
    storage_result: dict[str, Any],
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
        "database": str(database_path),
        "storage": storage_result,
    }


async def receive_one_update(
    ticker: str,
    timeout_seconds: float,
    database_path: str | Path = DEFAULT_DATABASE,
) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    recorder = MarketRecorder(database_path)
    queue: asyncio.Queue[tuple[dict[str, Any], datetime, dict[str, Any]]] = (
        asyncio.Queue(maxsize=1)
    )
    listener: asyncio.Task[None] | None = None
    connection_opened = False

    async def handle_message(message: dict[str, Any]) -> None:
        message_ticker = str(message.get("id", "")).upper()
        if message_ticker and message_ticker != symbol:
            return

        if queue.empty():
            receipt_time = datetime.now(timezone.utc)
            storage_result = recorder.record_message(
                message,
                receipt_time,
                ticker=symbol,
            ).to_dict()
            queue.put_nowait((message, receipt_time, storage_result))

    async def handle_connected() -> None:
        nonlocal connection_opened
        connection_opened = True

    try:
        async with asyncio.timeout(timeout_seconds):
            listener = asyncio.create_task(
                listen_for_updates(symbol, handle_message, handle_connected)
            )
            message, receipt_time, storage_result = await queue.get()
            return format_update(
                symbol,
                message,
                receipt_time,
                timeout_seconds,
                recorder.path,
                storage_result,
            )
    except TimeoutError:
        return {
            "ticker": symbol,
            "connection_opened": connection_opened,
            "receipt_verified": False,
            "timeout_seconds": timeout_seconds,
            "observation": "No matching update arrived before the bounded timeout.",
            "database": str(recorder.path),
        }
    except Exception as error:
        return {
            "ticker": symbol,
            "connection_opened": connection_opened,
            "receipt_verified": False,
            "timeout_seconds": timeout_seconds,
            "error": f"{type(error).__name__}: {error}",
            "database": str(recorder.path),
        }
    finally:
        try:
            if listener is not None:
                listener.cancel()
            if listener is not None:
                with suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.wait_for(listener, timeout=4)
        finally:
            recorder.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Receive at most one Yahoo Finance WebSocket update.",
    )
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    arguments = parser.parse_args()

    if arguments.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    result = asyncio.run(
        receive_one_update(
            arguments.ticker,
            arguments.timeout,
            arguments.database,
        ),
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
