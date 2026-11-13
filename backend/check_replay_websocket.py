import argparse
import asyncio
import json
from urllib.request import urlopen

from websockets.asyncio.client import connect


async def collect(url: str) -> list[dict]:
    messages = []
    async with connect(url) as websocket:
        async for payload in websocket:
            messages.append(json.loads(payload))
    return messages


async def main_async(base_http: str, base_ws: str) -> None:
    with urlopen(f"{base_http}/api/replay/selections") as response:
        selections = json.load(response)

    replay_url = (
        f"{base_ws}/ws/replay?symbol=AAPL&timeframe=1m"
        "&start=2026-11-09T14%3A59%3A00Z"
        "&end=2026-11-09T15%3A01%3A00Z&speed=1000"
    )
    first = await collect(replay_url)
    second = await collect(replay_url)
    empty = await collect(
        f"{base_ws}/ws/replay?symbol=AAPL&timeframe=1m"
        "&start=2026-11-10T14%3A59%3A00Z"
        "&end=2026-11-10T15%3A01%3A00Z&speed=1000"
    )
    first_complete = first[-1]
    second_complete = second[-1]
    observed = next(
        candle
        for candle in first_complete["final_candles"]
        if candle["timestamp"] == "2026-11-09T15:00:00Z"
    )
    expected = {
        "timestamp": "2026-11-09T15:00:00Z",
        "open": 100.0,
        "high": 103.0,
        "low": 100.0,
        "close": 102.0,
        "volume": 12,
    }
    result = {
        "selection_response": selections,
        "first_types": [message["type"] for message in first],
        "first_observed_candle": observed,
        "expected_candle": expected,
        "checks": {
            "live_feed_is_disabled": selections["live_feed_enabled"] is False,
            "expected_values_match": observed == expected,
            "second_run_is_identical": first_complete == second_complete,
            "observation_count_unchanged": (
                first_complete["stored_observation_count_before"]
                == first_complete["stored_observation_count_after"]
                == second_complete["stored_observation_count_before"]
                == second_complete["stored_observation_count_after"]
                == 5
            ),
            "empty_selection_is_reported": (
                empty[0]["type"] == "replay_empty"
                and empty[0]["message"]
                == "This selection has no recorded observations."
            ),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if not all(result["checks"].values()):
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", default="http://127.0.0.1:8000")
    parser.add_argument("--ws", default="ws://127.0.0.1:8000")
    args = parser.parse_args()
    asyncio.run(main_async(args.http, args.ws))


if __name__ == "__main__":
    main()
