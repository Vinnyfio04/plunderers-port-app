"""TEST DATA: bar revisions, tick overlay, volume replacement, and fetch failure."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

from backend.live_candles import CandleClient, CandleHub, TEST_SOURCE
from backend.market_store import MarketRecorder
from backend.recorded_history import recorded_history
from backend.yahoo_history import fetch_recent, save_bars, market_status


def time(value):
    return datetime.fromisoformat('2026-11-09T' + value + '+00:00')


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


async def check():
    root = Path(__file__).parent / 'data' / 'smoke-runs'
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        db = Path(folder) / 'bars.sqlite3'
        candle = dict(timestamp='2026-11-09T15:00:00Z', open=100, high=102, low=99, close=101, volume=10)
        save_bars(db, 'AAPL', [candle], time('15:00:30'))
        hub = CandleHub(db, test_feed=True)
        ws = Socket()
        hub.clients[1] = CandleClient(ws, 'AAPL', '1m')
        payload = {'id': 'AAPL', 'time': int(time('15:00:40').timestamp()*1000),
                   'price': 104, 'day_volume': 9000, 'test_data': True, 'test_data_label': TEST_SOURCE}
        await hub.publish_observation('AAPL', payload, time('15:00:41'), TEST_SOURCE)
        overlay = ws.messages[-1]['candle']
        assert overlay == {**candle, 'high': 104, 'close': 104, 'volume': None}
        final = {**candle, 'high': 105, 'close': 103, 'volume': 25}
        save_bars(db, 'AAPL', [final], time('15:01:10'))
        await hub.broadcast_candles('AAPL', time('15:01:11'), TEST_SOURCE)
        assert ws.messages[-1]['candle'] == final  # 25, not 10 + 25 or a tick total
        save_bars(db, 'AAPL', [final], time('15:01:12'))
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT COUNT(*) FROM yahoo_minute_bars').fetchone()[0] == 2
        revised = {**final, 'volume': 30}
        save_bars(db, 'AAPL', [revised], time('15:01:20'))
        assert recorded_history(db, 'AAPL', '1m', time('15:01:15'))['candles'][-1]['volume'] == 25
        assert recorded_history(db, 'AAPL', '1m', time('15:01:21'))['candles'][-1]['volume'] == 30
        save_bars(db, 'AAPL', [final], time('15:01:22'))  # revision reverting to prior payload
        assert recorded_history(db, 'AAPL', '5m', time('15:01:23'))['candles'][-1]['volume'] == 25
        with patch('backend.yahoo_history.yf.Ticker', side_effect=RuntimeError('TEST failure')):
            failed = fetch_recent(db)
        assert failed['status'] == 'unavailable'
        assert recorded_history(db, 'AAPL', '1m')['candles'][-1] == final
        assert recorded_history(db, 'AAPL', '1m', time('14:59:59'))['candles'] == []
        saturday = market_status(datetime(2026,11,14,19,tzinfo=timezone.utc))
        assert saturday['status'] == 'closed' and saturday['next_open'] == '2026-11-16T14:30:00Z'
        assert market_status(time('15:00:00'))['status'] == 'open'
        next_tick = {**payload, 'time': int(time('15:01:05').timestamp()*1000), 'price': 106, 'day_volume': 9005}
        await hub.publish_observation('AAPL', next_tick, time('15:01:25'), TEST_SOURCE)
        next_result = recorded_history(db, 'AAPL', '1m', time('15:01:26'))
        assert len(next_result['candles']) == 2
        assert next_result['candles'][0] == final
        assert next_result['candles'][1]['close'] == 106
        early = market_status(datetime(2026,11,27,18,1,tzinfo=timezone.utc))
        assert early['status'] == 'closed' and early['session_close'] == '2026-11-27T18:00:00Z'
        await hub.close()
        print(json.dumps({'label': 'TEST DATA — Yahoo history reconciliation', 'checks': 'PASS',
                          'overlay': overlay, 'completed': final, 'Saturday': saturday,
                          'verified': ['tick overlay', 'no volume double count', 'identical fetch',
                                       'revision and reverted revision', 'as-of cutoff', 'reopen',
                                       'failure cache', '5m aggregation', 'open/closed/early close']}, indent=2))


if __name__ == '__main__':
    asyncio.run(check())
