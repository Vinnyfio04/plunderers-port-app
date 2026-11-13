import argparse
import asyncio
import json
from pathlib import Path

import websockets

from backend.market_store import MarketRecorder


TEST_SOURCE = "TEST DATA — recorded interface verification input"
CANDLE_FIELDS = {"timestamp", "open", "high", "low", "close", "volume"}


async def collect_until_upstream_disconnect(url: str) -> dict:
    messages = []
    async with websockets.connect(url) as websocket:
        while True:
            message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
            messages.append(message)
            if message["type"] == "status" and message["feed_status"] == "disconnected":
                break
        pong = await websocket.ping()
        await asyncio.wait_for(pong, timeout=2)
        browser_connection_remained_open = True

    candle_messages = [message for message in messages if message["type"] == "candle"]
    return {
        "messages": messages,
        "candle_messages": candle_messages,
        "browser_connection_remained_open": browser_connection_remained_open,
    }


async def run_checks(base_url: str, database_path: Path) -> dict:
    one_minute = await collect_until_upstream_disconnect(
        f"{base_url}?symbol=AAPL&timeframe=1m"
    )
    five_minute = await collect_until_upstream_disconnect(
        f"{base_url}?symbol=AAPL&timeframe=5m"
    )

    one_minute_candles = one_minute["candle_messages"]
    final_1500 = next(
        message
        for message in reversed(one_minute_candles)
        if message["candle"]["timestamp"] == "2026-11-09T15:00:00Z"
    )
    final_1501 = one_minute_candles[-1]
    five_minute_final = five_minute["candle_messages"][-1]

    with MarketRecorder(database_path) as recorder:
        observations = recorder.list_observations()
        receipts = recorder.list_receipts()
    source_row = next(
        observation
        for observation in observations
        if observation["source_time_utc"] == "2026-11-09T15:00:50Z"
    )

    checks = {
        "same_minute_updated_in_place": (
            sum(
                message["candle"]["timestamp"] == "2026-11-09T15:00:00Z"
                for message in one_minute_candles
            )
            == 3
            and final_1500["candle"]
            == {
                "timestamp": "2026-11-09T15:00:00Z",
                "open": 100.0,
                "high": 103.0,
                "low": 100.0,
                "close": 101.0,
                "volume": 11,
            }
        ),
        "next_minute_started_new_candle": final_1501["candle"]
        == {
            "timestamp": "2026-11-09T15:01:00Z",
            "open": 102.0,
            "high": 102.0,
            "low": 102.0,
            "close": 102.0,
            "volume": 4,
        },
        "five_minute_uses_same_backend_aggregation": (
            five_minute_final["interval"] == "5m"
            and five_minute_final["candle"]
            == {
                "timestamp": "2026-11-09T15:00:00Z",
                "open": 100.0,
                "high": 103.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 15,
            }
        ),
        "message_candle_has_exact_fields": all(
            set(message["candle"]) == CANDLE_FIELDS for message in one_minute_candles
        ),
        "message_carries_context": all(
            message["symbol"] == "AAPL"
            and message["interval"] == "1m"
            and message["source"] == TEST_SOURCE
            and "feed_status" in message
            and "completion" in message
            for message in one_minute_candles
        ),
        "stored_source_matches_candle_close": (
            source_row["price"] == final_1500["candle"]["close"]
            and source_row["day_volume"] == 1011
            and source_row["source_time_utc"] == "2026-11-09T15:00:50Z"
        ),
        "upstream_disconnect_is_separate": (
            one_minute["browser_connection_remained_open"]
            and one_minute["messages"][-1]["feed_status"] == "disconnected"
        ),
        "test_input_was_stored_once": len(observations) == 5,
        "repeat_replay_kept_receipt_audit": len(receipts) == 10,
    }
    if not all(checks.values()):
        raise AssertionError(f"live candle verification failed: {checks}")

    return {
        "data_label": TEST_SOURCE,
        "database": str(database_path),
        "stored_source_row": {
            "observation_id": source_row["observation_id"],
            "ticker": source_row["ticker"],
            "source_time_utc": source_row["source_time_utc"],
            "price": source_row["price"],
            "day_volume": source_row["day_volume"],
        },
        "one_minute_candle": final_1500["candle"],
        "next_one_minute_candle": final_1501["candle"],
        "five_minute_candle": five_minute_final["candle"],
        "completion": final_1501["completion"],
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the FastAPI live-candle WebSocket test feed.",
    )
    parser.add_argument("--url", default="ws://127.0.0.1:8014/ws/candles")
    parser.add_argument("--database", type=Path, required=True)
    arguments = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run_checks(arguments.url, arguments.database.resolve())),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
