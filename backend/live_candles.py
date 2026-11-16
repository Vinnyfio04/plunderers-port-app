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
from backend.candle_store import finish_minutes, epoch, stamp, session_bounds, session_for
import random


YAHOO_SOURCE = "Yahoo Finance"
TEST_SOURCE = "TEST DATA — recorded interface verification input"


@dataclass
class CandleClient:
    websocket: WebSocket
    symbol: str
    timeframe: Timeframe
    sent: dict | None = None
    cursor: int = 0
    daily_cursor: int = 0
    interval_cursor: int = 0
    queue: Any = None
    sender: Any = None


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
        self.continuous = False
        self.writer = None
        self.manual_test = os.getenv('MARKET_MANUAL_TEST_FEED','0')=='1'
        self.latest_metadata = {}
        self.completion_task = None
        self.last_seen_wall = {}
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
        client = self.clients[client_id]
        client.queue = asyncio.Queue(maxsize=256)
        client.sender = asyncio.create_task(self._sender(client_id,client))
        if not self.test_feed:
            initial = recorded_history(self.database_path, symbol, timeframe,self._now() if self.manual_test else None,
                                       apply_policy=self.continuous and not self.manual_test)
            client.cursor = initial['watermark']
            client.daily_cursor = initial.get('daily_watermark',0)
            client.interval_cursor = initial.get('interval_watermark',0)
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
        if not self.manual_test and (symbol not in self.tasks or self.tasks[symbol].done()):
            task = asyncio.create_task(self._run_feed(symbol))
            self.tasks[symbol] = task
        return client_id

    def _now(self):
        if self.manual_test:
            with MarketRecorder(self.database_path) as store:
                value = store.connection.execute('SELECT MAX(receipt_ms) FROM receipts').fetchone()[0]
                if value:
                    return datetime.fromtimestamp(value/1000,timezone.utc)
        return datetime.now(timezone.utc)

    async def remove_client(self, client_id: int) -> None:
        client = self.clients.pop(client_id, None)
        if client is None:
            return
        if client.sender:
            client.sender.cancel()
        if not self.continuous and not any(other.symbol == client.symbol for other in self.clients.values()):
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
        if self.completion_task:
            await self.completion_task
        tasks = list(self.tasks.values())
        self.tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        for client_id in list(self.clients):
            await self.remove_client(client_id)

    async def start(self, writer=None):
        self.continuous = True
        self.writer = writer
        if self.clock_task is None:
            self.clock_task = asyncio.create_task(self._clock())
        self.tasks['AAPL'] = asyncio.create_task(self._supervise('AAPL'))

    async def _supervise(self, symbol):
        delay = 1
        previous_open = False
        while True:
            state = market_status()
            if state['status'] != 'open':
                await self._broadcast_status(symbol,'market_closed',YAHOO_SOURCE)
                previous_open = False
                await asyncio.sleep(min(30,max(1,(datetime.fromisoformat(state['next_open'].replace('Z','+00:00'))-datetime.now(timezone.utc)).total_seconds())))
                continue
            if not previous_open:
                delay = 1
                previous_open = True
            await self._run_feed(symbol)
            await asyncio.sleep(min(60,delay)+random.random())
            delay = min(60,delay*2)

    async def _sender(self, client_id, client):
        try:
            while True:
                message = await client.queue.get()
                await asyncio.wait_for(client.websocket.send_json(message),timeout=5)
        except (Exception, asyncio.CancelledError):
            self.clients.pop(client_id,None)
            try:
                await client.websocket.close(code=1013)
            except Exception:
                pass

    async def _clock(self):
        cycles = 0
        while True:
            await asyncio.sleep(.25)
            cycles += 1
            if not self.test_feed and cycles % 4 == 0:
                def finish():
                    with MarketRecorder(self.database_path) as store:
                        finish_minutes(store.connection,self._now())
                if self.writer:
                    if self.completion_task is None or self.completion_task.done():
                        self.completion_task = asyncio.create_task(self.writer.run(finish))
                else:
                    finish()
            for symbol in {client.symbol for client in self.clients.values()}:
                now = self._now()
                storage, source_time = self.latest_metadata.get(symbol,(None,None))
                age = max(0,(now-datetime.fromisoformat(source_time.replace('Z','+00:00'))).total_seconds()) if source_time else None
                source = 'TEST DATA — continuous browser fixture' if self.manual_test else YAHOO_SOURCE
                await self.broadcast_candles(symbol,now,source,storage,source_time,age)
                if cycles % 120 == 0:
                    if market_status(now)['status']=='open' and self.feed_status.get(symbol) in ('connected','live'):
                        seen = self.last_seen_wall.get(symbol,now)
                        if (now-seen).total_seconds()>30:
                            self.feed_status[symbol] = 'stale'
                    await self._broadcast_status(symbol, self.feed_status.get(symbol, 'connecting'), YAHOO_SOURCE)

    async def broadcast_candles(self, symbol, now, source, storage=None, source_time=None, source_age=None):
        if not self.test_feed:
            await self._broadcast_changes(symbol,now,source,storage,source_time,source_age)
            return
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

    async def _broadcast_changes(self,symbol,now,source,storage,source_time,source_age):
        for client_id,client in list(self.clients.items()):
            if client.symbol != symbol:
                continue
            with MarketRecorder(self.database_path) as store:
                changes = store.connection.execute('''SELECT revision_id,minute_start FROM candle_revisions
                    WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?) AND revision_id>?
                    ORDER BY revision_id LIMIT 513''',(symbol,client.cursor)).fetchall()
                daily_changes = store.connection.execute('''SELECT revision_id,timestamp,session_close FROM daily_revisions
                    WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?) AND revision_id>?
                    ORDER BY revision_id LIMIT 513''',(symbol,client.daily_cursor)).fetchall() if client.timeframe=='1d' else []
                interval_changes = store.connection.execute('''SELECT revision_id,timestamp,interval_end FROM interval_revisions
                    WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?) AND interval=? AND revision_id>?
                    ORDER BY revision_id LIMIT 513''',(symbol,client.timeframe,client.interval_cursor)).fetchall() if client.timeframe in ('5m','15m','1h') else []
            if not changes and not daily_changes and not interval_changes:
                continue
            if len(changes)+len(daily_changes)+len(interval_changes)>512:
                initial = recorded_history(self.database_path,symbol,client.timeframe,apply_policy=self.continuous and not self.manual_test)
                await self._send_json(client_id,dict(type='history',symbol=symbol,interval=client.timeframe,**initial))
                client.cursor = initial['watermark']
                client.daily_cursor = initial.get('daily_watermark',0)
                client.interval_cursor = initial.get('interval_watermark',0)
                continue
            groups = set()
            groups.update((r['timestamp'],r['session_close']) for r in daily_changes)
            groups.update((r['timestamp'],r['interval_end']) for r in interval_changes)
            for row in changes:
                start = row['minute_start']
                bounds = session_bounds(stamp(start)[:10])
                minutes = {'1m':1,'5m':5,'15m':15,'1h':60,'1d':390}[client.timeframe]
                beginning = bounds[0] if client.timeframe=='1d' else bounds[0]+((start-bounds[0])//(minutes*60))*(minutes*60)
                groups.add((beginning,min(beginning+minutes*60,bounds[1])))
            for beginning,end in sorted(groups):
                result = recorded_history(self.database_path,symbol,client.timeframe,now if self.manual_test else None,
                    start=stamp(beginning),before=stamp(end),apply_policy=self.continuous and not self.manual_test)
                for candle,completion in zip(result['candles'],result['status']):
                    await self._send_json(client_id,dict(type='candle',symbol=symbol,interval=client.timeframe,
                        source=completion.get('price_source',source),feed_status=self.feed_status.get(symbol,'connecting'),source_time=source_time,
                        source_age_seconds=source_age,backend_receipt_time=now.isoformat(),storage=storage,
                        candle=candle,completion=completion,market=result['market'],
                        watermark=changes[-1]['revision_id'] if changes else client.cursor,
                        daily_watermark=daily_changes[-1]['revision_id'] if daily_changes else client.daily_cursor,
                        interval_watermark=interval_changes[-1]['revision_id'] if interval_changes else client.interval_cursor))
            if changes:
                client.cursor = changes[-1]['revision_id']
            if daily_changes:
                client.daily_cursor = daily_changes[-1]['revision_id']
            if interval_changes:
                client.interval_cursor = interval_changes[-1]['revision_id']

    async def _run_feed(self, symbol: str) -> None:
        if self.test_feed:
            await self._run_test_feed(symbol)
            return

        async def connected() -> None:
            self.last_seen_wall[symbol] = datetime.now(timezone.utc)
            await self._broadcast_status(symbol, "connected", YAHOO_SOURCE)

        async def received(message: dict[str, Any]) -> None:
            message_symbol = str(message.get("id") or symbol).upper()
            if message_symbol == symbol:
                receipt_time = datetime.now(timezone.utc)
                operation = lambda: self.publish_observation(symbol,message,receipt_time,YAHOO_SOURCE,broadcast=False)
                if self.writer:
                    await self.writer.run(operation)
                else:
                    await operation()

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
        broadcast: bool = True,
    ) -> None:
        source_time = describe_source_time(message.get("time"))["source_time_utc"]
        self.last_seen_wall[symbol] = receipt_time
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
            # Paper valuations need only the immediately preceding completed minute.
            recent = recorded_history(self.database_path,symbol,'1m',limit=2)

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
                for candle, status in zip(recent['candles'],recent['status'])
                if status['interval_ended']
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

        source_minute = epoch(source_time)//60000*60 if source_time else None
        if source_minute is None or session_for(source_minute) is None:
            await self._broadcast_status(
                symbol,
                "outside_regular_session",
                source,
                detail="The observation did not map to an XNYS regular-session candle.",
                source_time=source_time,
                source_age_seconds=source_age,
            )
            return

        self.feed_status[symbol] = 'delayed' if source_age is not None and source_age>60 else 'live'
        self.latest_metadata[symbol] = (storage,source_time)
        if broadcast:
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
            table = 'daily_history_fetches' if client.timeframe=='1d' else 'interval_history_fetches' if client.timeframe in ('5m','15m','1h') else 'yahoo_history_fetches'
            scope = ' AND interval=?' if table=='interval_history_fetches' else ''
            latest_fetch = recorder.connection.execute(f'''SELECT status, fetched_at, message FROM {table}
                WHERE ticker=?{scope} ORDER BY fetch_id DESC LIMIT 1''',
                (client.symbol,client.timeframe) if scope else (client.symbol,)).fetchone()
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
                "market": market_status(self._now()),
                "history_fetch": dict(latest_fetch) if latest_fetch else None,
            },
        )

    async def _send_json(self, client_id: int, message: dict[str, Any]) -> None:
        client = self.clients.get(client_id)
        if client is None:
            return
        if client.queue is not None:
            try:
                client.queue.put_nowait(message)
            except asyncio.QueueFull:
                await self.remove_client(client_id)
                await client.websocket.close(code=1013)
            return
        try:
            await client.websocket.send_json(message)
        except Exception:
            self.clients.pop(client_id, None)
