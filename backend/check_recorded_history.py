"""Offline TEST DATA regression for recorded startup and streamed revisions."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from backend.live_candles import CandleClient, CandleHub, TEST_SOURCE
from backend.market_store import MarketRecorder
from backend.recorded_history import recorded_history


def utc(value):
    return datetime.fromisoformat('2026-11-09T' + value + '+00:00')


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


async def check():
    runs = Path(__file__).parent / 'data' / 'smoke-runs'
    runs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runs) as folder:
        db = Path(folder) / 'test.sqlite3'
        hub = CandleHub(db, test_feed=True)
        ws = Socket()
        hub.clients[1] = CandleClient(ws, 'AAPL', '1m')
        assert recorded_history(db, 'AAPL', '1m')['candles'] == []
        async def send(time, price, volume, receipt=None):
            payload = {'id': 'AAPL', 'time': int(utc(time).timestamp()*1000),
                       'price': price, 'test_data': True, 'test_data_label': TEST_SOURCE}
            if volume is not None:
                payload['day_volume'] = volume
            await hub.publish_observation('AAPL', payload, utc(receipt or time), TEST_SOURCE)
            return payload
        await send('14:59:59', 99, 1000)
        await send('15:00:05', 100, 1004)
        await send('15:00:50', 101, 1011)
        await hub.broadcast_candles('AAPL', utc('15:01:00'), TEST_SOURCE)
        ended = ws.messages[-1]
        assert ended['completion']['interval_ended']
        await send('15:01:05', 102, 1015)
        repeat = await send('15:00:20', 103, 1009, '15:01:10')
        assert ws.messages[-1]['candle']['timestamp'] == '2026-11-09T15:00:00Z'
        assert ws.messages[-1]['candle']['high'] == 103
        with MarketRecorder(db) as store:
            original = store.record_message(repeat, utc('15:01:11'), ticker='AAPL')
            revised = {**repeat, 'price': 104}
            store.record_message(revised, utc('15:01:12'), ticker='AAPL',
                                 supersedes_observation_id=original.observation_id)
            assert len(store.list_observations()) == 6
            assert len(store.list_receipts()) == 7
        await hub.broadcast_candles('AAPL', utc('15:01:13'), TEST_SOURCE)
        assert any(m.get('candle', {}).get('high') == 104 for m in ws.messages)
        before = recorded_history(db, 'AAPL', '1m', utc('15:01:11'))
        after = recorded_history(db, 'AAPL', '1m', utc('15:01:13'))
        assert before['candles'][1]['high'] == 103
        assert after['candles'][1] == dict(timestamp='2026-11-09T15:00:00Z',
                                         open=100, high=104, low=100, close=101, volume=11)
        await send('15:03:05', 105, 1030)
        assert ws.messages[-1]['candle']['volume'] is None  # no baseline in previous minute
        await send('15:04:05', 106, 2)
        assert ws.messages[-1]['candle']['volume'] is None  # reset
        await send('15:05:05', 107, None)
        assert ws.messages[-1]['candle']['volume'] is None
        await hub._broadcast_status('AAPL', 'disconnected', TEST_SOURCE)
        assert ws.messages[-1]['feed_status'] == 'disconnected'
        with MarketRecorder(db) as store:
            count = store.connection.execute('SELECT COUNT(*) FROM candle_states').fetchone()[0]
            assert count > 0
        reopened = recorded_history(db, 'AAPL', '1m', utc('15:01:13'))
        assert reopened['candles'] == after['candles']
        await hub.close()
        print(json.dumps({'label': TEST_SOURCE, 'checks': 'PASS',
            'final_1500': after['candles'][1], 'persisted_candle_states': count,
            'verified': ['empty history', 'arrival cutoff', 'repeat', 'late candle broadcast',
                         'revision', 'timer completion', 'volume gaps/resets/missing',
                         'feed disconnect', 'database reopen']}, indent=2))


if __name__ == '__main__':
    asyncio.run(check())
