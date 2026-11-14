import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import json
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from backend.candle_aggregation import aggregate_ticker
from backend.market_store import DEFAULT_DATABASE, MarketRecorder, describe_source_time
from backend.paper_trading import PaperAccount, dollars_to_cents
from backend.timeframe_history import Timeframe
from backend.yahoo_stream import listen_for_updates
from backend.recorded_history import recorded_history
from backend.yahoo_history import market_status, initialize


YAHOO_SOURCE = "Yahoo Finance"
TEST_SOURCE = "TEST DATA — recorded interface verification input"


@dataclass
class CandleClient:
    websocket: WebSocket
    symbol: str
    timeframe: Timeframe
    sent: dict | None = None


class CandleHub:
    def __init__(
        self,
        database_path: str | Path | None = None,
        test_feed: bool | None = None,
        paper_account: PaperAccount | None = None,
    ):
        configured_database = database_path or os.getenv(
            "MARKET_DATABASE",
            str(DEFAULT_DATABASE),
        )
        self.database_path = Path(configured_database).expanduser().resolve()
        initialize(self.database_path)
        self.test_feed = (
            test_feed
            if test_feed is not None
            else os.getenv("MARKET_TEST_FEED", "0") == "1"
        )
        self.paper_account = paper_account
        self.clients: dict[int, CandleClient] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.feed_status: dict[str, str] = {}
        self._next_client_id = 1
        self.clock_task = None
        with MarketRecorder(self.database_path) as recorder:
            recorder.connection.execute('''CREATE TABLE IF NOT EXISTS candle_states (
                state_id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, interval TEXT NOT NULL,
                timestamp TEXT NOT NULL, evaluated_at TEXT NOT NULL, candle_json TEXT NOT NULL,
                completion_json TEXT NOT NULL, UNIQUE(ticker, interval, timestamp, candle_json, completion_json))''')
            recorder.connection.commit()

    async def add_client(
        self,
        websocket: WebSocket,
        symbol: str,
        timeframe: Timeframe,
    ) -> int:
        await websocket.accept()
        client_id = self._next_client_id
        self._next_client_id += 1
        self.clients[client_id] = CandleClient(websocket, symbol, timeframe)
        if not self.test_feed:
            initial = recorded_history(self.database_path, symbol, timeframe)
            self.clients[client_id].sent = {
                c['timestamp']: json.dumps([c, s], sort_keys=True)
                for c, s in zip(initial['candles'], initial['status'])}
            await self._send_json(client_id, {'type': 'history', 'symbol': symbol,
                'interval': timeframe, **initial})
        if not self.test_feed and (self.clock_task is None or self.clock_task.done()):
            self.clock_task = asyncio.create_task(self._clock())
        await self._send_status(
            client_id,
            self.feed_status.get(symbol, "connecting"),
            source=TEST_SOURCE if self.test_feed else YAHOO_SOURCE,
        )
        if symbol not in self.tasks or self.tasks[symbol].done():
            task = asyncio.create_task(self._run_feed(symbol))
            self.tasks[symbol] = task
        return client_id

    async def remove_client(self, client_id: int) -> None:
        client = self.clients.pop(client_id, None)
        if client is None:
            return
        if not any(other.symbol == client.symbol for other in self.clients.values()):
            task = self.tasks.pop(client.symbol, None)
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            self.feed_status[client.symbol] = "stopped"

    async def close(self) -> None:
        if self.clock_task:
            self.clock_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.clock_task
        tasks = list(self.tasks.values())
        self.tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self.clients.clear()

    async def _clock(self):
        cycles = 0
        while True:
            await asyncio.sleep(1)
            cycles += 1
            for symbol in {client.symbol for client in self.clients.values()}:
                await self.broadcast_candles(symbol, datetime.now(timezone.utc), YAHOO_SOURCE)
                if cycles % 30 == 0:
                    await self._broadcast_status(symbol, self.feed_status.get(symbol, 'connecting'), YAHOO_SOURCE)

    async def broadcast_candles(self, symbol, now, source, storage=None, source_time=None, source_age=None):
        for client_id, client in list(self.clients.items()):
            if client.symbol != symbol:
                continue
            result = recorded_history(self.database_path, symbol, client.timeframe, now)
            if client.sent is None:
                client.sent = {}
            for candle, completion in zip(result['candles'], result['status']):
                state = json.dumps([candle, completion], sort_keys=True)
                if client.sent.get(candle['timestamp']) == state:
                    continue
                client.sent[candle['timestamp']] = state
                with MarketRecorder(self.database_path) as recorder:
                    recorder.connection.execute('''INSERT OR IGNORE INTO candle_states
                        (ticker, interval, timestamp, evaluated_at, candle_json, completion_json)
                        VALUES (?,?,?,?,?,?)''', (symbol, client.timeframe, candle['timestamp'],
                        now.isoformat(), json.dumps(candle, sort_keys=True), json.dumps(completion, sort_keys=True)))
                    recorder.connection.commit()
                await self._send_json(client_id, {
                    'type': 'candle', 'symbol': symbol, 'interval': client.timeframe,
                    'source': source, 'feed_status': self.feed_status.get(symbol, 'connecting'),
                    'source_time': source_time, 'source_age_seconds': source_age,
                    'backend_receipt_time': now.isoformat(), 'storage': storage,
                    'completion': completion, 'candle': candle,
                    'market': result['market'], 'history_fetch': result['history_fetch'],
                })

    async def _run_feed(self, symbol: str) -> None:
        if self.test_feed:
            await self._run_test_feed(symbol)
            return

        async def connected() -> None:
            await self._broadcast_status(symbol, "connected", YAHOO_SOURCE)

        async def received(message: dict[str, Any]) -> None:
            message_symbol = str(message.get("id") or symbol).upper()
            if message_symbol == symbol:
                await self.publish_observation(
                    symbol,
                    message,
                    datetime.now(timezone.utc),
                    YAHOO_SOURCE,
                )

        failed = False
        try:
            await self._broadcast_status(symbol, "connecting", YAHOO_SOURCE)
            await listen_for_updates(symbol, received, connected)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failed = True
            await self._broadcast_status(
                symbol,
                "error",
                YAHOO_SOURCE,
                detail=f"{type(error).__name__}: {error}",
            )
        finally:
            if symbol in self.tasks and not failed:
                await self._broadcast_status(symbol, "disconnected", YAHOO_SOURCE)

    async def publish_observation(
        self,
        symbol: str,
        message: dict[str, Any],
        receipt_time: datetime,
        source: str,
    ) -> None:
        source_time = describe_source_time(message.get("time"))["source_time_utc"]
        source_age = None
        if source_time is not None:
            parsed_source = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
            source_age = max(0.0, (receipt_time - parsed_source).total_seconds())

        with MarketRecorder(self.database_path) as recorder:
            storage = recorder.record_message(
                message,
                receipt_time,
                ticker=symbol,
            ).to_dict()
            one_minute = aggregate_ticker(recorder, symbol, receipt_time)

        if self.paper_account is not None and message.get("price") is not None:
            self.paper_account.process_market_observation(
                symbol=symbol,
                price=message["price"],
                observation_id=storage["observation_id"],
                receipt_id=storage["receipt_id"],
                arrival_time=receipt_time,
                source=source,
            )

        if self.paper_account is not None:
            ended = [
                (candle, status)
                for candle, status in zip(one_minute.candles, one_minute.minute_status)
                if status["ended"]
            ]
            if ended:
                completed, _ = ended[-1]
                self.paper_account.record_completed_candle_valuation(
                    event_key=(
                        f"completed-candle:{symbol}:1m:{completed['timestamp']}:"
                        f"close-cents:{dollars_to_cents(completed['close'])}"
                    ),
                    symbol=symbol,
                    price=completed["close"],
                    event_time=receipt_time,
                    source=f"{source} · completed 1m candle",
                    observation_id=storage["observation_id"],
                    receipt_id=storage["receipt_id"],
                )

        if not one_minute.candles:
            await self._broadcast_status(
                symbol,
                "outside_regular_session",
                source,
                detail="The observation did not map to an XNYS regular-session candle.",
                source_time=source_time,
                source_age_seconds=source_age,
            )
            return

        self.feed_status[symbol] = "live"
        await self.broadcast_candles(symbol, receipt_time, source, storage, source_time, source_age)

    async def _run_test_feed(self, symbol: str) -> None:
        await self._broadcast_status(symbol, "connected", TEST_SOURCE)
        test_messages = [
            ("2026-11-09T14:59:59Z", 99, 1000),
            ("2026-11-09T15:00:05Z", 100, 1004),
            ("2026-11-09T15:00:20Z", 103, 1009),
            ("2026-11-09T15:00:50Z", 101, 1011),
            ("2026-11-09T15:01:05Z", 102, 1015),
        ]
        for source_time, price, volume in test_messages:
            parsed = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
            message = {
                "id": symbol,
                "time": int(parsed.timestamp() * 1000),
                "price": price,
                "day_volume": volume,
                "test_data": True,
                "test_data_label": TEST_SOURCE,
            }
            await self.publish_observation(
                symbol,
                message,
                parsed,
                TEST_SOURCE,
            )
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.3)
        await self._broadcast_status(
            symbol,
            "disconnected",
            TEST_SOURCE,
            detail="Test upstream disconnected; FastAPI WebSocket remains open.",
        )

    async def _broadcast_status(
        self,
        symbol: str,
        status: str,
        source: str,
        detail: str | None = None,
        source_time: str | None = None,
        source_age_seconds: float | None = None,
    ) -> None:
        self.feed_status[symbol] = status
        for client_id, client in list(self.clients.items()):
            if client.symbol == symbol:
                await self._send_status(
                    client_id,
                    status,
                    source,
                    detail,
                    source_time,
                    source_age_seconds,
                )

    async def _send_status(
        self,
        client_id: int,
        status: str,
        source: str,
        detail: str | None = None,
        source_time: str | None = None,
        source_age_seconds: float | None = None,
    ) -> None:
        client = self.clients.get(client_id)
        if client is None:
            return
        with MarketRecorder(self.database_path) as recorder:
            latest_fetch = recorder.connection.execute('''SELECT status, fetched_at, message FROM yahoo_history_fetches
                WHERE ticker=? ORDER BY fetch_id DESC LIMIT 1''', (client.symbol,)).fetchone()
        await self._send_json(
            client_id,
            {
                "type": "status",
                "symbol": client.symbol,
                "interval": client.timeframe,
                "source": source,
                "feed_status": status,
                "detail": detail,
                "source_time": source_time,
                "source_age_seconds": source_age_seconds,
                "market": market_status(),
                "history_fetch": dict(latest_fetch) if latest_fetch else None,
            },
        )

    async def _send_json(self, client_id: int, message: dict[str, Any]) -> None:
        client = self.clients.get(client_id)
        if client is None:
            return
        try:
            await client.websocket.send_json(message)
        except Exception:
            self.clients.pop(client_id, None)
